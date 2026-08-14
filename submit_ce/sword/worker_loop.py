"""Find SWORD deposits waiting to be processed, and process them.

`submit_ce.sword.worker.advance` handles one submission; this decides which ones
and keeps going. Run it as a Cloud Run Job or any long-lived process::

    python -m submit_ce.sword.worker_loop            # one pass, then exit
    python -m submit_ce.sword.worker_loop --forever  # poll until stopped

Why polling rather than a queue
-------------------------------
Preflight and compile take up to 840 seconds each and hold the submission's row
lock throughout, so the work cannot ride on the deposit request. A queue with
callbacks would work, but it needs the Cloud Run request timeout raised past half
an hour, an authenticated internal endpoint, and queue IAM. Polling needs a
database query. At SWORD's volume -- a handful of automated depositors -- the only
thing it costs is latency, bounded by the poll interval.

Retries come free: a submission that fails is simply still a candidate next pass,
except where `advance` deliberately stops (see its dead ends), which it does by
recording state rather than by tracking attempts.

One worker at a time
--------------------
The candidate query uses ``SELECT ... FOR UPDATE SKIP LOCKED``, so a second worker
steps over submissions that are mid-preflight or mid-compile instead of blocking on
the row lock for up to 840 seconds. That removes the stall, but it is not a lease:
`advance` commits between steps, and the lock dies with its transaction, so two
workers can still both claim a submission in the gaps. Because every step re-checks
durable state, the cost is a wasted pass rather than corruption -- but a duplicate
compile is possible.

**One worker remains the supported deployment.** See `candidates` for what would be
needed to make more than one safe.
"""

import argparse
import logging
import sys
import time
from typing import Iterable, List, Optional, Set

import arxiv.db.models as models
from sqlalchemy import select
from sqlalchemy.orm import Session as SqlalchemySession

from submit_ce.api import SubmitApi
from submit_ce.domain.agent import Client, InternalClient, PublicUser, User
from submit_ce.sword.worker import Outcome, advance

logger = logging.getLogger(__name__)

WORKING = 0
"""``arXiv_submissions.status`` for a submission still being prepared.

`FinalizeSubmission` moves it to SUBMITTED, which is what takes a submission out of
the candidate set.
"""

TRACKING_IN_PROGRESS_PREFIX = "submit/"
"""What `ingest.record_tracking` writes into ``arXiv_tracking.paper_id`` until the
paper is announced. Kept in step with `ingest.TRACKING_IN_PROGRESS`."""

MAX_ERROR_LENGTH = 2000
"""``submission_errors`` is TEXT, but a compile service can return a great deal of
it; the useful part is at the front."""

DEFAULT_INTERVAL = 60
"""Seconds between passes in ``--forever``. Deposits arrive in batches from a few
automated clients, so there is nothing to gain from polling harder."""


def _has_recorded_failure():
    """Correlated EXISTS: this submission's tracking row records a failure.

    Joined on ``sword_id``, the foreign key `ingest.record_tracking` sets on both
    rows, rather than by parsing the id back out of ``paper_id``.

    ``EXISTS`` rather than ``NOT IN`` deliberately. A ``NOT IN`` over a subquery
    that yields even one NULL evaluates to NULL for every row, so the candidate
    set silently empties -- which is exactly what happened when this was first
    written against ``substr(paper_id)``.
    """
    return (select(models.Tracking.sword_id)
            .where(models.Tracking.sword_id == models.Submission.sword_id,
                   models.Tracking.submission_errors.isnot(None))
            .exists())


def record_failure(session: SqlalchemySession, submission_id: int,
                   message: str) -> None:
    """Record a permanent failure on the deposit's tracking row.

    This is what stops the submission being a candidate, and it is also what makes
    the failure visible: ``/resolve/app/<sword_id>`` reads this row, so a depositor
    polling for their deposit sees why it stopped instead of watching it sit at
    ``incomplete`` forever.

    Legacy wrote the same column for the same purpose -- the processing fork's
    ``UPDATE arXiv_tracking SET submission_errors=?`` (``AtomPP.pm:1321-1325``).
    """
    submission = session.get(models.Submission, submission_id)
    row = None
    if submission is not None and submission.sword_id is not None:
        row = (session.query(models.Tracking)
               .filter_by(sword_id=submission.sword_id).one_or_none())
    if row is None:
        logger.warning("submission %s has no tracking row; failure not recorded",
                       submission_id)
        return
    row.submission_errors = message[:MAX_ERROR_LENGTH]
    session.commit()
    logger.info("recorded permanent failure for submission %s", submission_id)


def candidates(session: SqlalchemySession,
               limit: Optional[int] = None,
               exclude: Optional[Iterable[int]] = None) -> List[int]:
    """Submission ids for SWORD deposits that still need processing.

    ``sword_id`` is the discriminator: it is set by `ingest.record_tracking` and
    is null for everything created through the web UI, which has its own path
    through these steps and must not be driven from here.

    Oldest first, so a backlog drains in the order it arrived rather than starving
    the earliest deposit.

    ``FOR UPDATE SKIP LOCKED`` steps over rows another worker is currently working
    on. What it does and does not buy is worth being precise about:

    * `SubmitApi.save` locks the submission row for the whole of preflight and of
      compile -- the two long operations. A second worker selecting during those
      windows skips the row instead of blocking on it for up to 840 seconds, which
      is the failure this prevents.
    * It is **not** a lease. The lock lives only as long as the transaction that
      took it, and `advance` commits between steps, so the row is briefly
      unlocked several times per submission. Two workers can still both select the
      same submission in those gaps. Every step re-checks durable state before
      acting, so the cost is a wasted pass rather than corruption -- but a
      duplicate compile is possible.
    * Closing that gap properly needs a lock that outlives a transaction: MySQL's
      ``GET_LOCK``/``RELEASE_LOCK`` keyed on the submission id, or a lease column.
      Neither is here, so **one worker remains the supported deployment**; this
      makes a second one merely wasteful rather than a 14-minute stall.

    Requires MySQL 8.0 or later. SQLAlchemy's SQLite dialect silently omits the
    whole clause -- no error, no locking -- so tests exercise the predicate and
    ordering but never the locking itself.
    """
    stmt = (select(models.Submission.submission_id)
            .where(models.Submission.sword_id.isnot(None),
                   models.Submission.status == WORKING,
                   ~_has_recorded_failure())
            .order_by(models.Submission.submission_id.asc())
            .with_for_update(skip_locked=True))
    if exclude:
        stmt = stmt.where(models.Submission.submission_id.notin_(list(exclude)))
    if limit is not None:
        stmt = stmt.limit(limit)
    return [row for row in session.execute(stmt).scalars().all()]


def actor_for(session: SqlalchemySession, submission_id: int) -> User:
    """The user the worker acts as: the account that deposited the submission.

    Events are attributed to the depositor rather than to a system agent so the
    submission's history reads the same as an interactive one, and so anything
    keyed on the creator (notifications, ownership) behaves normally.
    """
    row = session.get(models.Submission, submission_id)
    user = session.get(models.TapirUser, row.submitter_id) if row else None
    if user is None:
        raise LookupError(f"submission {submission_id} has no submitter")
    return PublicUser(user_id=str(user.user_id),
                      name=user.first_name or "",
                      email=user.email or "",
                      endorsements=[])


def worker_client() -> Client:
    """The client recorded on the worker's events."""
    return InternalClient(agent_type="InternalClient", name="sword-worker")


def configure_database() -> None:
    """Point `arxiv.db.Session` at the configured database.

    Must run before any query. `config_backend_api` sets only the session
    factory's *default* bind, and that is not what a query on
    ``arxiv.db.models.Submission`` uses: `arxiv.db` binds per model, so without
    ``db.init`` that model resolves to arxiv-base's own default
    (``sqlite:///tests/data/browse.db``) and the query fails with "unable to open
    database file" -- while ``Session.get_bind()`` and `SubmitApi.healthy` both
    report the right engine, because they use the default bind.

    `create_sword_app` does the same two things for the same reason.
    """
    from arxiv import db
    from arxiv.config import settings as base_settings

    from submit_ce.ui.config import settings

    base_settings.CLASSIC_DB_URI = settings.CLASSIC_DB_URI
    db.init(settings)


def run_once(api: SubmitApi, session: SqlalchemySession,
             limit: Optional[int] = None) -> List[Outcome]:
    """Advance every waiting deposit as far as it will go.

    Claims one submission at a time rather than listing them all up front, so
    ``SKIP LOCKED`` is evaluated immediately before each is worked on. Selecting a
    batch would be pointless: `advance` commits, which drops every lock the batch
    query took, leaving the rest of the list unprotected for the whole pass.

    ``attempted`` is what terminates the loop. A submission that fails is still a
    candidate -- deliberately, so the next pass retries it -- and without excluding
    it here this would select it forever.
    """
    outcomes: List[Outcome] = []
    attempted: Set[int] = set()

    while limit is None or len(attempted) < limit:
        found = candidates(session, limit=1, exclude=attempted)
        if not found:
            break
        submission_id = found[0]
        attempted.add(submission_id)

        try:
            outcome = advance(api, str(submission_id),
                              creator=actor_for(session, submission_id),
                              client=worker_client())
        except Exception:
            # One bad submission must not stop the pass. The next pass will try it
            # again -- right for a transient fault, and harmless for a permanent
            # one because `advance` re-checks state rather than repeating work.
            logger.exception("submission %s could not be processed",
                             submission_id)
            continue
        logger.info("%s", outcome)
        if outcome.permanent and outcome.error:
            record_failure(session, submission_id, outcome.error)
        outcomes.append(outcome)

    if not attempted:
        logger.debug("no SWORD deposits waiting")
    return outcomes


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--forever", action="store_true",
                        help="keep polling instead of exiting after one pass")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help=f"seconds between passes (default {DEFAULT_INTERVAL})")
    parser.add_argument("--limit", type=int, default=None,
                        help="process at most this many submissions per pass")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    # Imported here, not at module scope: building the API opens the database and
    # the file store, which a --help should not do.
    from arxiv.db import Session
    from submit_ce.implementations.legacy_implementation.fastapi_impl import (
        FastapiSubmitImplementation,
    )
    from submit_ce.implementations.wiring import config_backend_api
    from submit_ce.ui.config import settings

    configure_database()
    api = config_backend_api(settings, impl=FastapiSubmitImplementation)

    if not args.forever:
        run_once(api, Session, args.limit)
        return 0

    logger.info("polling every %ds; Ctrl-C to stop", args.interval)
    while True:
        try:
            run_once(api, Session, args.limit)
        except Exception:
            logger.exception("pass failed; continuing")
        finally:
            Session.remove()    # do not hold a connection across the sleep
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
