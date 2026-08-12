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
There is no claim or lease. Two workers running together would both pick up the
same submission, and the second would block on the row lock `SubmitApi.save` takes
-- for up to the full compile timeout -- before discovering the work was done.
Deploy this with a concurrency of one. At current volume a single worker keeps up
easily; if that changes, the fix is ``SELECT ... FOR UPDATE SKIP LOCKED`` over the
candidate query, not more workers against this one.
"""

import argparse
import logging
import sys
import time
from typing import List, Optional

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

DEFAULT_INTERVAL = 60
"""Seconds between passes in ``--forever``. Deposits arrive in batches from a few
automated clients, so there is nothing to gain from polling harder."""


def candidates(session: SqlalchemySession,
               limit: Optional[int] = None) -> List[int]:
    """Submission ids for SWORD deposits that still need processing.

    ``sword_id`` is the discriminator: it is set by `ingest.record_tracking` and
    is null for everything created through the web UI, which has its own path
    through these steps and must not be driven from here.

    Oldest first, so a backlog drains in the order it arrived rather than starving
    the earliest deposit.
    """
    stmt = (select(models.Submission.submission_id)
            .where(models.Submission.sword_id.isnot(None),
                   models.Submission.status == WORKING)
            .order_by(models.Submission.submission_id.asc()))
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


def run_once(api: SubmitApi, session: SqlalchemySession,
             limit: Optional[int] = None) -> List[Outcome]:
    """Advance every waiting deposit as far as it will go."""
    ids = candidates(session, limit)
    if not ids:
        logger.debug("no SWORD deposits waiting")
        return []

    logger.info("%d SWORD deposit(s) waiting", len(ids))
    outcomes = []
    for submission_id in ids:
        try:
            outcome = advance(api, str(submission_id),
                              creator=actor_for(session, submission_id),
                              client=worker_client())
        except Exception:
            # One bad submission must not stop the rest of the batch. The next
            # pass will try it again -- which is right for a transient fault, and
            # harmless for a permanent one because `advance` re-checks state
            # rather than repeating work.
            logger.exception("submission %s could not be processed",
                             submission_id)
            continue
        logger.info("%s", outcome)
        outcomes.append(outcome)
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
