"""
Integration with the classic database to persist events and submission state.

As part of the classic renewal strategy, development of new submission
interfaces must maintain data interoperability with classic components. This
service module must therefore do three main things:

1. Store and provide access to event data generated during the submission
   process,
2. Keep the classic database tables up to date so that "downstream" components
   can continue to operate.
3. Patch NG submission data with state changes that occur in the classic
   system. Those changes will be made directly to submission tables and not
   involve event-generation. See :func:`get_submission` for details.

Since classic components work directly on submission tables, persisting events
and resulting submission state must occur in the same transaction. We must also
verify that we are not storing events that are stale with respect to the
current state of the submission. To achieve this, the caller should use the
:func:`.util.transaction` context manager, and (when committing new events)
call :func:`.get_submission` with ``for_update=True``. This will trigger a
shared lock on the submission row(s) involved until the transaction is
committed or rolled back.

ORM representations of the classic database tables involved in submission
are located in :mod:`.classic.models`. An additional model, :class:`.DBEvent`,
is defined in :mod:`.classic.event`.

See also :ref:`legacy-integration`.

"""

import copy
import traceback
from datetime import datetime
from functools import wraps
from itertools import groupby
from operator import attrgetter
from typing import Dict, List, Optional, Tuple, Callable, Any, TypeVar, cast, \
    Iterable
import logging

from arxiv.license import LICENSES
from pydantic import RootModel
from retry import retry as _retry
from sqlalchemy import or_, func
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session as SQLAlchemySession
from sqlalchemy.orm.exc import NoResultFound

from submit_ce.domain.agent import Client, HttpClient, System
from submit_ce.domain.event.legacy import Withdraw
from submit_ce.domain.event.request import CancelRequest, RequestWithdrawal

from . import models, interpolate, log
from .models import DBEvent
from .patch import patch_cross, patch_hold, patch_jref, patch_withdrawal
from submit_ce import domain
from submit_ce.domain.uploads import SourceFormat
from submit_ce.domain import Event, Submission, User, WithdrawalRequest, CrossListClassificationRequest,  License
from submit_ce.domain.submission import SubmissionType
from submit_ce.domain.event import CreateSubmission, CreateJrefSubmission, \
    CreateCrossSubmission, Rollback, ProposeClassification
from submit_ce.domain.exceptions import NoSuchSubmission, NoSuchDocument

logger = logging.getLogger(__name__)
logger.propagate = False

FuncType = Callable[..., Any]
F = TypeVar('F', bound=FuncType)

# retry = _retry
retry: Callable[..., Callable[[F], F]] = _retry


# wraps: Callable[[F], F] = _wraps


def handle_operational_errors(func: F) -> F:
    """Catch SQLAlchemy OperationalErrors and raise :class:`.Unavailable`."""

    @wraps(func)
    def inner(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except OperationalError as e:
            logger.error('Encountered an OperationalError calling %s',
                         func.__name__)
            # This will put the traceback in the log, and it may look like an
            # unhandled exception (even though it is not).
            logger.error('==== OperationalError: handled traceback start ====')
            logger.error(traceback.format_exc())
            logger.error('==== OperationalError: handled traceback end ====')
            raise OperationalError('Classic database unavailable',
                                   getattr(e, 'params', None),
                                   getattr(e, 'orig', e)) from e

    # return inner
    return cast(F, inner)


@retry(OperationalError, tries=3, delay=1)
@handle_operational_errors
def get_licenses(session: SQLAlchemySession) -> List[License]:
    """Get a list of :class:`.domain.License` instances available."""
    license_data = session.query(models.License) \
        .filter(models.License.active == '1')
    return [License(uri=row.name, name=row.label) for row in license_data]


@retry(OperationalError, tries=3, delay=1)
@handle_operational_errors
def get_events(session: SQLAlchemySession, submission_id: str) -> List[Event]:
    """
    Load events from the classic database.

    Parameters
    ----------
    submission_id : str

    Returns
    -------
    list
        Items are :class:`.Event` instances loaded from the class DB.

    Raises
    ------
    :class:`.classic.exceptions.NoSuchSubmission`
        Raised when there are no events for the provided submission ID.

    """
    event_data = session.query(DBEvent) \
        .filter(DBEvent.submission_id == submission_id) \
        .order_by(DBEvent.created)
    events = [datum.to_event() for datum in event_data]
    if not events:  # No events, no dice.
        logger.error('No events for submission %s', submission_id)
        raise NoSuchSubmission(f'Submission {submission_id} not found')
    return events


# @retry(ClassicBaseException, tries=3, delay=1)
@handle_operational_errors
def get_submission(session: SQLAlchemySession, submission_id: str, for_update: bool = False) \
        -> Tuple[Submission, List[Event]]:
    """
    Get the current state of a submission from the database.

    In the medium term, services that use this package will need to
    play well with legacy services that integrate with the classic
    database. For example, the moderation system does not use the event
    model implemented here, and will therefore cause direct changes to the
    submission tables that must be reflected in our representation of the
    submission.

    Until those legacy components are replaced, this function loads both the
    event stack and the current DB state of the submission, and uses the DB
    state to patch fields that may have changed outside the purview of the
    event model.

    Parameters
    ----------
    submission_id : str

    Returns
    -------
    :class:`.domain.submission.Submission`
    list
        Items are :class:`Event` instances.

    """
    # Let the caller determine the transaction scope.
    original_row = session.query(models.Submission) \
        .filter(models.Submission.submission_id == submission_id) \
        .join(DBEvent)

    if for_update:
        # Gives us SELECT ... FOR READ. In other words, lock this row for
        # writing, but allow other clients to read from it in the meantime.
        original_row = original_row.with_for_update(read=True)

    try:
        original_row = original_row.one()
        logger.debug('Got row %s', original_row)
    except NoResultFound as exc:
        logger.debug('Got NoResultFound exception %s', exc)
        raise NoSuchSubmission(f'Submission {submission_id} not found')
        # May also raise MultipleResultsFound; if so, we want to fail loudly.

    # Load any subsequent submission rows (e.g. v=2, jref, withdrawal).
    # These do not have the same legacy submission ID as the original
    # submission.
    subsequent_rows: List[models.Submission] = []
    arxiv_id = original_row.get_arxiv_id()
    if arxiv_id is not None:
        subsequent_query = session.query(models.Submission) \
            .filter(models.Submission.doc_paper_id == arxiv_id) \
            .filter(models.Submission.submission_id != submission_id) \
            .order_by(models.Submission.submission_id.asc())

        if for_update:  # Lock these rows as well.
            subsequent_query = subsequent_query.with_for_update(read=True)
        subsequent_rows = list(subsequent_query)  # Execute query.
        logger.debug('Got subsequent_rows: %s', subsequent_rows)

    try:
        _events = get_events(session, submission_id)
    except NoSuchSubmission:
        _events = []

    # If this submission originated in the classic system, we will have usable
    # rows from the submission table, and either no events or events that do
    # not start with a CreateSubmission event. In that case, fall back to
    # ``load.load()``, which relies only on classic rows.
    if not _events or not isinstance(_events[0], CreateSubmission):
        logger.info('Loading a classic submission: %s', submission_id)
        submission = load([original_row] + subsequent_rows)
        if submission is None:
            raise NoSuchSubmission('No such submission')
        return submission, []

    # We have an NG-native submission.
    interpolator = interpolate.ClassicEventInterpolator(
        original_row,
        subsequent_rows,
        _events
    )
    return interpolator.get_submission_state()


# @retry(ClassicBaseException, tries=3, delay=1)
@handle_operational_errors
def store_event(session: SQLAlchemySession, event: Event, before: Optional[Submission], after: Submission) -> Tuple[Event, Submission]:
    """
    Store an event, and update submission state.

    This is where we map the NG event domain onto the classic database. The
    main differences are that:

    - In the event domain, a submission is a single stream of events, but
      in the classic system we create new rows in the submission database
      for things like replacements, adding DOIs, and withdrawing papers.
    - In the event domain, the only concept of the announced paper is the
      paper ID. In the classic submission database, we also have to worry about
      the row in the Document database.

    We assume that the submission states passed to this function have the
    correct paper ID and version number, if announced. The submission ID on
    the event and the before/after states refer to the original classic
    submission only.

    Parameters
    ----------
    session: :class:`SQLAlchemySession`
        DB session to use when storing. `commit()` should not be called inside `store_event` so that code
        using `store_event` can manage the transaction.
    event : :class:`Event`
    before : :class:`Submission`
        The state of the submission before the event occurred.
    after : :class:`Submission`
        The state of the submission after the event occurred.
    """
    # Let the caller determine the transaction scope.
    if event.committed:
        raise ValueError(f'{event.event_type} {event.event_id} already committed')
    if event.created is None:
        raise ValueError('Event creation timestamp not set')
    logger.debug('store event %s', event.event_type)

    doc_id: Optional[int] = None
    # This is the case that we have a new submission.
    if before is None:  # and isinstance(after, Submission):
        dbs = models.Submission(type=models.Submission.NEW_SUBMISSION)
        dbs.update_from_submission(after)
        this_is_a_new_submission = True

    else:  # Otherwise we're making an update for an existing submission.
        this_is_a_new_submission = False

        if before.arxiv_id is not None:  #:
            # After the original submission is announced, a new Document row is
            # created. This Document is shared by all subsequent Submission rows.
            doc_id = _load_document_id(session, before.arxiv_id, before.version)

            # From the perspective of the database, a replacement is mainly an
            # incremented version number. This requires a new row in the
            # database.
            if after.version > before.version:
                dbs = _create_replacement(doc_id, before.arxiv_id,
                                          after.version, after, event.created)
            elif isinstance(event, Rollback) and before.version > 1:
                dbs = _delete_replacement(session, doc_id, before.arxiv_id,
                                          before.version)


            # Withdrawals also require a new row, and they use the most recent
            # version number.
            elif isinstance(event, RequestWithdrawal):
                dbs = _create_withdrawal(doc_id, event.reason,
                                         before.arxiv_id, after.version, after,
                                         event.created)
            elif isinstance(event, CancelRequest):
                dbs = _cancel_request(session, event, before, after)

            # A jref or a cross is its own row, but it carries the announced
            # paper's `doc_paper_id`, so it lands in this branch. Each must be
            # loaded by its own submission id: `_load` by paper_id defaults to
            # the new/rep rows and would return the announced row instead.
            elif before.submission_type == SubmissionType.JOURNAL_REFERENCE:
                dbs = _load(session, submission_id=before.submission_id,
                            row_type=models.Submission.JOURNAL_REFERENCE)
                _preserve_sticky_hold(dbs, before, after, event)
                dbs.update_from_submission(after)

            elif before.submission_type == SubmissionType.CROSS_LIST:
                dbs = _load(session, submission_id=before.submission_id,
                            row_type=models.Submission.CROSS_LIST)
                _preserve_sticky_hold(dbs, before, after, event)
                dbs.update_from_submission(after)

            # The submission has been announced.
            # TODO Redundant logic in this next clause
            elif isinstance(before, Submission) and before.arxiv_id is not None:
                dbs = _load(session, paper_id=before.arxiv_id, version=before.version)
                _preserve_sticky_hold(dbs, before, after, event)
                dbs.update_from_submission(after)
            else:
                raise ValueError(f"Cannot handle {event.event_type} already announced. paper_id: {before.paper_id}")

        # The submission has not yet been announced; we're working with a single row.
        elif isinstance(before, Submission) and before.submission_id:
            dbs = _load(session, before.submission_id)

            _preserve_sticky_hold(dbs, before, after, event)
            dbs.update_from_submission(after)
        else:
            raise ValueError(f"Cannot handle submission of type {type(before)} and event {type(event)}")

    # Make sure that we get a submission ID; note that this does not commit
    # the transaction, just pushes the SQL that we have generated so far to the db.
    session.add(dbs)
    session.flush([dbs])

    # at this point a new submission will have a submission_id
    if this_is_a_new_submission:
        event.submission_id = dbs.submission_id

    # Attach the row for Event to the submission
    db_event = _new_dbevent(event)
    session.add(db_event)
    event.committed = True

    log.handle(session, event, before, after)  # Create admin log entry.

    # Update the domain event and submission states with the submission ID.
    # This should carry forward the original submission ID, even if the
    # classic database has several rows for the submission (with different
    # IDs).
    if this_is_a_new_submission:
        event.submission_id = dbs.submission_id
        after.submission_id = dbs.submission_id
    else:
        assert before is not None
        event.submission_id = before.submission_id
        after.submission_id = before.submission_id

    # Some events also write to auxiliary classic tables, keyed off the now-final
    # submission_id. A category proposal records a row in
    # arXiv_submission_category_proposal (and an accompanying admin log comment).
    if isinstance(event, ProposeClassification):
        _store_proposal(session, event, after)

    return event, after


def _store_proposal(session: SQLAlchemySession, event: ProposeClassification,
                    after: Submission) -> models.CategoryProposal:
    """Record a category proposal in the classic database.

    Mirrors the legacy ``system_propose_primary`` / ``save_new_proposals``
    behaviour: insert one ``arXiv_submission_category_proposal`` row with
    ``proposal_status = UNRESOLVED`` and an ``arXiv_admin_log`` comment row,
    linked via ``proposal_comment_id``.
    """
    assert event.category is not None
    user_id = _proposer_user_id(session, event.creator)

    type_str = "primary" if event.is_primary else "secondary"
    logtext = f"Proposed: {event.category} as {type_str}"
    if event.comment:
        logtext += f": {event.comment}"
    username = "system" if isinstance(event.creator, System) \
        else str(event.creator.identifier)
    comment = log.admin_log(session, "Submission", "admin comment", logtext,
                            username=username,
                            submission_id=after.submission_id)
    # Flush so the comment row gets an id to reference from the proposal.
    if comment is not None:
        session.flush([comment])

    proposal = models.CategoryProposal(
        submission_id=after.submission_id,
        category=event.category,
        is_primary=1 if event.is_primary else 0,
        proposal_status=models.CategoryProposal.UNRESOLVED,
        user_id=user_id,
        updated=event.created,
        proposal_comment_id=comment.id if comment is not None else None,
    )
    session.add(proposal)
    session.flush([proposal])
    return proposal


def _proposer_user_id(session: SQLAlchemySession, creator: User) -> int:
    """Resolve the tapir ``user_id`` for the agent making a proposal.

    Moderators carry their own tapir id; system/classifier proposals are
    attributed to the configured ``system`` user (legacy looks this up by the
    ``system`` nickname in ``tapir_nicknames``).
    """
    if isinstance(creator, System):
        row = session.query(models.Username) \
            .filter_by(nickname="system").first()
        if row is None:
            raise RuntimeError(
                "No 'system' user configured for system-generated proposals")
        return int(row.user_id)
    return int(creator.identifier)


def _load(session: SQLAlchemySession,
          submission_id: Optional[str] = None, paper_id: Optional[str] = None,
          version: Optional[int] = 1, row_type: Optional[str] = None) \
        -> models.Submission:
    if row_type is not None:
        limit_to = [row_type]
    else:
        limit_to = [models.Submission.NEW_SUBMISSION,
                    models.Submission.REPLACEMENT]
    if submission_id is not None:
        submission = session.query(models.Submission) \
            .filter(models.Submission.submission_id == submission_id) \
            .filter(models.Submission.type.in_(limit_to)) \
            .one()
    elif submission_id is None and paper_id is not None:
        submission = session.query(models.Submission) \
            .filter(models.Submission.doc_paper_id == paper_id) \
            .filter(models.Submission.version == version) \
            .filter(models.Submission.type.in_(limit_to)) \
            .order_by(models.Submission.submission_id.desc()) \
            .first()
    else:
        submission = None
    if submission is None:
        raise NoSuchSubmission("No submission row matches those parameters")
    assert isinstance(submission, models.Submission)
    return submission


def _cancel_request(session: SQLAlchemySession, event: CancelRequest, before: Submission,
                    after: Submission) -> models.Submission:
    assert event.request_id is not None
    request = before.user_requests[event.request_id]
    if isinstance(request, WithdrawalRequest):
        row_type = models.Submission.WITHDRAWAL
    elif isinstance(request, CrossListClassificationRequest):
        row_type = models.Submission.CROSS_LIST
    dbs = _load(session, paper_id=before.arxiv_id, version=before.version,
                row_type=row_type)
    dbs.status = models.Submission.USER_DELETED
    return dbs


def _load_document_id(session: SQLAlchemySession, paper_id: str, version: int) -> int:
    document_id = session.query(models.Submission.document_id) \
        .filter(models.Submission.doc_paper_id == paper_id) \
        .filter(models.Submission.version == version) \
        .filter(models.Submission.document_id.isnot(None)) \
        .order_by(models.Submission.submission_id.desc()) \
        .first()
    if document_id is None or document_id[0] is None:
        raise NoSuchSubmission(f"No submission row with paper_id {paper_id} and version {version}")
    return int(document_id[0])


def _create_replacement(document_id: int, paper_id: str, version: int,
                        submission: Submission, created: datetime) \
        -> models.Submission:
    """
    Create a new replacement submission.

    From the perspective of the database, a replacement is mainly an
    incremented version number. This requires a new row in the database.
    """
    # remote_addr/remote_host have to be passed here, as the withdrawal and JREF
    # constructors below also do: update_from_submission() only sets them on the
    # initial row (`version == 1 and type == NEW_SUBMISSION`, models.py:365-369),
    # where the guard was written for `created` and swept them along. Both columns
    # are NOT NULL, so omitting them loses the depositor's address on MySQL and
    # fails outright on a backend without the DDL default.
    dbs = models.Submission(type=models.Submission.REPLACEMENT,
                            document_id=document_id, version=version,
                            remote_addr=submission.client.remote_addr,
                            remote_host=submission.client.remote_host)
    dbs.update_from_submission(submission)
    dbs.created = created
    dbs.updated = created
    dbs.doc_paper_id = paper_id
    dbs.status = models.Submission.WORKING
    return dbs


def _delete_replacement(session: SQLAlchemySession, document_id: int, paper_id: str, version: int) \
        -> models.Submission:
    dbs = session.query(models.Submission) \
        .filter(models.Submission.doc_paper_id == paper_id) \
        .filter(models.Submission.version == version) \
        .filter(models.Submission.type == models.Submission.REPLACEMENT) \
        .order_by(models.Submission.submission_id.desc()) \
        .first()
    dbs.status = models.Submission.USER_DELETED
    assert isinstance(dbs, models.Submission)
    return dbs


def _create_withdrawal(document_id: int, reason: str, paper_id: str,
                       version: int, submission: Submission,
                       created: datetime) -> models.Submission:
    """
    Create a new withdrawal request.

    Withdrawals also require a new row, and they use the most recent version
    number.
    """
    dbs = models.Submission(type=models.Submission.WITHDRAWAL,
                            document_id=document_id,
                            version=version,
                            remote_addr=submission.client.remote_addr,
                            remote_host=submission.client.remote_host,
                            )
    dbs.update_withdrawal(submission, reason, paper_id, version, created)
    return dbs


def load_latest_announced(session: SQLAlchemySession, paper_id: str) \
        -> models.Submission:
    """Load the most recent announced version row for ``paper_id``.

    Used to seed a withdrawal from the metadata of the latest version.
    """
    max_version = session.query(func.max(models.Submission.version)) \
        .filter(models.Submission.doc_paper_id == paper_id) \
        .filter(models.Submission.type.in_([models.Submission.NEW_SUBMISSION,
                                            models.Submission.REPLACEMENT])) \
        .scalar()
    if max_version is None:
        raise NoSuchSubmission(f"No announced submission for paper {paper_id}")
    return _load(session, paper_id=paper_id, version=max_version)


def store_withdrawal(session: SQLAlchemySession, event: Withdraw,
                     seed: Submission) -> Tuple[Event, Submission]:
    """Create a new ``wdr`` submission row from a `Withdraw` event.

    Unlike :func:`store_event`, a withdrawal is a side-effecting event that
    *creates* a new row. We create and flush the row here so the new
    submission id exists, then hand the projected `after` (carrying the new id)
    back so the caller can run ``execute()`` against the new workspace.
    """
    if event.committed:
        raise ValueError(f'{event.event_type} {event.event_id} already committed')
    if event.created is None:
        raise ValueError('Event creation timestamp not set')

    after = event.apply(seed)
    doc_id = _load_document_id(session, event.paper_id, after.version)
    dbs = _create_withdrawal(doc_id, event.comment, event.paper_id,
                             after.version, after, event.created)
    dbs.is_withdrawn = 1

    # Flush to assign the autoincrement submission id for the new row.
    session.add(dbs)
    session.flush([dbs])

    # The new row owns its own workspace, keyed by the new submission id.
    after.submission_id = str(dbs.submission_id)
    dbs.package = str(dbs.submission_id)
    event.submission_id = str(dbs.submission_id)

    db_event = _new_dbevent(event)
    session.add(db_event)
    event.committed = True

    log.handle(session, event, seed, after)
    return event, after


def store_jref_create(session: SQLAlchemySession, event: CreateJrefSubmission,
                      seed: Submission) -> Tuple[Event, Submission]:
    """Create a new ``jref`` submission row from a `CreateJrefSubmission`.

    Like :func:`store_withdrawal`, and unlike :func:`store_event`, this
    *creates* a row rather than updating the one the event was saved against:
    a journal reference is its own submission. The row is flushed here so the
    returned ``after`` carries the new submission id.

    The row is left at ``WORKING``; a journal reference is not submitted until
    it is finalized, which matches legacy, where ``create_submission(...,
    'jref')`` makes the row at status 0.
    """
    return _store_create_against_paper(
        session, event, seed, models.Submission.JOURNAL_REFERENCE)


def store_cross_create(session: SQLAlchemySession,
                       event: CreateCrossSubmission,
                       seed: Submission) -> Tuple[Event, Submission]:
    """Create a new ``cross`` submission row from a `CreateCrossSubmission`.

    The cross-list counterpart of :func:`store_jref_create`, and the same shape:
    a cross-list is its own submission, created against an announced paper at
    classic status 0 (``WORKING``) with the announced version, not an
    incremented one.

    The categories the cross is adding are not written here. They arrive as
    later `AddCrossCategory` events and land through
    :meth:`.models.Submission._update_secondaries`; what this row gets at create
    time is the snapshot of the paper's current categories, all
    ``is_published = 1`` (legacy ``User::make_sub_cats``).
    """
    return _store_create_against_paper(
        session, event, seed, models.Submission.CROSS_LIST)


def _store_create_against_paper(session: SQLAlchemySession, event: Event,
                                seed: Submission, row_type: str) \
        -> Tuple[Event, Submission]:
    """Create the classic row for a submission made against an announced paper.

    Shared by :func:`store_jref_create` and :func:`store_cross_create`: both
    make a brand-new row of their own type against ``event.paper_id``, at the
    announced version and classic status 0, with no file side effect to sequence
    afterwards (unlike :func:`store_withdrawal`).
    """
    if event.committed:
        raise ValueError(f'{event.event_type} {event.event_id} already committed')
    if event.created is None:
        raise ValueError('Event creation timestamp not set')

    after = event.apply(seed)

    # Neither type increments the version, so this resolves the document of the
    # announced version being annotated.
    doc_id = _load_document_id(session, event.paper_id, after.version)

    # These columns are NOT NULL, so fall back to empty rather than None.
    client = after.client
    dbs = models.Submission(
        type=row_type,
        document_id=doc_id,
        version=after.version,
        remote_addr=str(client.remote_addr) if client and client.remote_addr else "",
        remote_host=(client.remote_host or "") if client else "")
    dbs.update_from_submission(after)
    dbs.created = event.created
    dbs.updated = event.created
    dbs.doc_paper_id = event.paper_id

    # Flush to assign the autoincrement submission id for the new row.
    session.add(dbs)
    session.flush([dbs])

    # Set the new db rows id on the event
    after.submission_id = str(dbs.submission_id)
    dbs.package = str(dbs.submission_id)
    event.submission_id = str(dbs.submission_id)

    db_event = _new_dbevent(event)
    session.add(db_event)
    event.committed = True

    log.handle(session, event, seed, after)
    return event, after


def _new_dbevent(event: Event) -> DBEvent:
    """Create an event entry in the database."""
    redundant_fields = {"creator", "proxy", "client", "created", "committed", "submission_id"}
    return DBEvent(event_type=event.event_type,
                   event_id=event.event_id,
                   submission_id=event.submission_id if event.submission_id else None,
                   event_version=_get_app_version(),
                   created=event.created,
                   data=event.model_dump_json(exclude=redundant_fields).encode('utf-8'),
                   creator=RootModel[User](event.creator).model_dump_json().encode('utf-8'),
                   client=RootModel[Client](event.client).model_dump_json().encode('utf-8') if event.client else None,
                   proxy=RootModel[User](event.proxy).model_dump_json().encode('utf-8') if event.proxy else None
                   )


def _preserve_sticky_hold(dbs: models.Submission, before: Submission,
                          after: Submission, event: Event) -> None:
    if dbs.status != models.Submission.ON_HOLD:
        return
    if dbs.is_on_hold() and after.status == Submission.WORKING:
        dbs.sticky_status = models.Submission.ON_HOLD


def _get_app_version() -> str:
    return '0.0.0'


def _get_db_submission_rows(session: SQLAlchemySession, submission_id: str) -> List[models.Submission]:
    head = session.query(models.Submission.submission_id,
                         models.Submission.doc_paper_id) \
        .filter_by(submission_id=submission_id) \
        .subquery()
    dbss = list(
        session.query(models.Submission)
        .filter(or_(models.Submission.submission_id == submission_id,
                    models.Submission.doc_paper_id == head.c.doc_paper_id))
        .order_by(models.Submission.submission_id.desc())
    )
    if not dbss:
        raise NoSuchSubmission('No submission found')
    return dbss


def to_submission(row: models.Submission,
                  submission_id: Optional[str] = None) -> domain.Submission:
    """
    Generate a representation of submission state from a DB instance.

    Parameters
    ----------
    row : :class:`.domain.Submission`
        Database row representing a :class:`.domain.submission.Submission`.
    submission_id : str or None
        If provided the database value is overridden when setting
        :attr:`domain.Submission.submission_id`.

    Returns
    -------
    :class:`.domain.submission.Submission`

    """

    status = row.status_from_classic()
    primary = row.primary_classification
    if row.submitter is None:
        submitter = domain.PublicUser(user_id=str(row.submitter_id),
                                      email=row.submitter_email,
                                      name=row.submitter_name)
    else:
        submitter = row.get_submitter()
    if submission_id is None:
        submission_id = str(row.submission_id)
    else:
        submission_id = str(submission_id)

    if row.proxy:
        proxy = str(row.proxy)
    else:
        proxy = None

    client = HttpClient(remote_addr=row.remote_addr,
                        remote_host=row.remote_host)

    license: Optional[domain.License] = None
    if row.license:
        label = LICENSES[row.license]['label']
        license = domain.License(uri=row.license, name=label)

    primary_clsn: Optional[domain.Classification] = None
    if primary and primary.category:
        primary_clsn = domain.Classification(
            category=primary.category,
            is_published=bool(primary.is_published))
    secondary_clsn = [
        domain.Classification(category=db_cat.category,
                              is_published=bool(db_cat.is_published))
        for db_cat in row.categories if not db_cat.is_primary
    ]

    source_format = SourceFormat(row.source_format) if row.package and row.source_format else None
    uncompressed_size = row.source_size if row.package else 0

    assert status is not None
    submission = domain.Submission(
        submission_id=submission_id,
        creator=submitter,
        owner=submitter,
        client=client,
        status=status,
        created=row.get_created(),
        updated=row.get_updated(),
        source_format=source_format,
        uncompressed_size=uncompressed_size,
        is_oversize=bool(row.is_oversize),
        submitter_is_author=bool(row.is_author),
        submitter_accepts_policy=bool(row.agree_policy),
        agreement_id=row.agreement_id,
        submitter_contact_verified=bool(row.userinfo),
        submitted=row.submit_time,
        is_source_processed=not bool(row.must_process),
        submitter_confirmed_preview=bool(row.viewed),
        metadata=domain.SubmissionMetadata(title=row.title,
                                           abstract=row.abstract,
                                           authors_display=row.authors,
                                           comments=row.comments,
                                           report_num=row.report_num,
                                           doi=row.doi,
                                           msc_class=row.msc_class,
                                           acm_class=row.acm_class,
                                           journal_ref=row.journal_ref),
        license=license,
        primary_classification=primary_clsn,
        secondary_classification=secondary_clsn,
        arxiv_id=row.doc_paper_id,
        version=row.version,
        submission_type=SubmissionType(row.type) if row.type else None,
        proxy=proxy
    )
    if row.sticky_status == row.ON_HOLD or row.status == row.ON_HOLD:
        submission = patch_hold(submission, row)

    for prop in row.category_proposals:
        submission.proposals[str(prop.proposal_id)] = _to_proposal(prop)

    return submission


def _to_proposal(row: models.CategoryProposal) -> domain.Proposal:
    """Build a domain :class:`.Proposal` from a classic proposal row."""
    proposer = row.user
    if proposer is not None:
        name = f"{proposer.first_name or ''} {proposer.last_name or ''}".strip()
        creator: domain.User = domain.PublicUser(
            user_id=str(row.user_id),
            name=name or "unknown",
            email=proposer.email or "unknown")
    else:
        creator = domain.PublicUser(user_id=str(row.user_id),
                                    name="unknown", email="unknown")
    comment = row.proposal_comment.logtext if row.proposal_comment else None

    if row.proposal_status in iter(domain.ProposalStatus):
        status = domain.ProposalStatus(row.proposal_status)
    else:
        status = domain.ProposalStatus.UNKNOWN

    return domain.Proposal(
        proposal_id=str(row.proposal_id),
        category=row.category,
        is_primary=bool(row.is_primary),
        creator=creator,
        created=row.updated,
        comment=comment,
        status=status,
        classic_proposal_id=row.proposal_id,
    )


def _to_document_metadata(row: models.Metadata) -> domain.DocMetadata:
    """Build a domain :class:`.DocMetadata` from an ``arXiv_metadata`` row."""
    return domain.DocMetadata(
        version=row.version,
        title=row.title,
        abstract=row.abstract,
        authors=row.authors,
        categories=row.abs_categories,
        comments=row.comments,
        report_num=row.report_num,
        msc_class=row.msc_class,
        acm_class=row.acm_class,
        journal_ref=row.journal_ref,
        doi=row.doi,
        license=row.license,
        source_size=row.source_size,
        source_format=row.source_format,
        submitter_name=row.submitter_name,
        submitter_email=row.submitter_email,
        submitter_id=row.submitter_id,
        created=row.created,
        updated=row.updated,
        is_current=bool(row.is_current),
        is_withdrawn=bool(row.is_withdrawn),
    )


def has_active_submission(session: SQLAlchemySession, paper_id: str,
                          exclude_submission_id: Optional[str] = None) -> bool:
    """Whether ``paper_id`` has an in-progress (non-announced, non-deleted) row.

    ``exclude_submission_id`` is ignored when checking, so a submission does not
    count itself as a conflict.
    """
    rows = session.query(models.Submission) \
        .filter(models.Submission.doc_paper_id == paper_id).all()
    for row in rows:
        if exclude_submission_id is not None \
                and str(row.submission_id) == str(exclude_submission_id):
            continue
        if row.is_active():
            return True
    return False


def to_document(session: SQLAlchemySession, paper_id: str) -> domain.Document:
    """Build a :class:`.domain.document.Document` for an announced paper.

    Composes the announced state from three classic tables: the submission rows
    (``arXiv_submissions``) for identity, version and the list of submissions;
    the per-version metadata (``arXiv_metadata``); and the current published
    categories (``arXiv_document_category``).

    Raises
    ------
    :class:`.NoSuchDocument`
        If there is no announced submission row for ``paper_id``.
    """
    rows = session.query(models.Submission) \
        .filter(models.Submission.doc_paper_id == paper_id) \
        .order_by(models.Submission.version.asc(),
                  models.Submission.submission_id.asc()) \
        .all()
    if not any(row.is_announced() for row in rows):
        raise NoSuchDocument(f"No announced paper {paper_id}")

    md_rows = session.query(models.Metadata) \
        .filter(models.Metadata.paper_id == paper_id) \
        .order_by(models.Metadata.version.asc()) \
        .all()

    document_id = _latest_announced(rows).document_id
    cat_rows: List[models.DocumentCategory] = []
    if document_id is not None:
        cat_rows = session.query(models.DocumentCategory) \
            .filter(models.DocumentCategory.document_id == document_id).all()

    return _assemble_document(paper_id, rows, md_rows, cat_rows)


def to_documents_for_user(session: SQLAlchemySession,
                          user_id: str) -> List[domain.Document]:
    """Build a :class:`.domain.document.Document` per announced paper of a user.

    TODO This is narrower than classic's ``arXiv_paper_owners``, which also
    carries ownership granted by a claim or by an administrator.
    """
    paper_ids = [row[0] for row in
                 session.query(models.Document.paper_id)
                 .filter(models.Document.submitter_id == int(user_id))
                 .order_by(models.Document.created.desc())
                 .all()]
    if not paper_ids:
        return []

    subs_for_paper: Dict[str, List[models.Submission]] = \
        {paper_id: [] for paper_id in paper_ids}
    for row in session.query(models.Submission) \
            .filter(models.Submission.doc_paper_id.in_(paper_ids)) \
            .order_by(models.Submission.version.asc(),
                      models.Submission.submission_id.asc()).all():
        subs_for_paper[row.doc_paper_id].append(row)

    # A paper's version, submitter and identity are read from its announced
    # submission row, so one without such a row cannot be assembled -- and could
    # not offer Replace/Withdraw/Add cross-list anyway, since all three are keyed
    # on that row's id. Classic has such papers: `arXiv_documents` reaches back
    # further than `arXiv_submissions` does.
    unannounced = [paper_id for paper_id in paper_ids
                   if not any(row.is_announced()
                              for row in subs_for_paper[paper_id])]
    if unannounced:
        logger.warning('User %s: skipping %d paper(s) with no announced'
                       ' submission row: %s', user_id, len(unannounced),
                       ', '.join(unannounced))
        paper_ids = [paper_id for paper_id in paper_ids
                     if paper_id not in set(unannounced)]
        if not paper_ids:
            return []

    md_by_paper: Dict[str, List[models.Metadata]] = \
        {paper_id: [] for paper_id in paper_ids}
    for md in session.query(models.Metadata) \
            .filter(models.Metadata.paper_id.in_(paper_ids)) \
            .order_by(models.Metadata.version.asc()).all():
        md_by_paper[md.paper_id].append(md)

    document_ids = {paper_id: _latest_announced(subs_for_paper[paper_id])
                    .document_id for paper_id in paper_ids}
    cats_by_document: Dict[int, List[models.DocumentCategory]] = {}
    known_ids = [doc_id for doc_id in document_ids.values()
                 if doc_id is not None]
    if known_ids:
        for cat in session.query(models.DocumentCategory) \
                .filter(models.DocumentCategory.document_id.in_(known_ids)) \
                .all():
            cats_by_document.setdefault(cat.document_id, []).append(cat)

    return [_assemble_document(paper_id,
                               subs_for_paper[paper_id],
                               md_by_paper[paper_id],
                               cats_by_document.get(document_ids[paper_id], []))
            for paper_id in paper_ids]


def _latest_announced(rows: Iterable[models.Submission]) -> models.Submission:
    """The announced row for the highest announced version of a paper.

    The row a paper's identity is read from. Raises `ValueError` on rows with no
    announced row among them; callers check for that first.
    """
    return max((row for row in rows if row.is_announced()),
               key=lambda r: (r.version, r.submission_id))


def _assemble_document(paper_id: str,
                       rows: List[models.Submission],
                       md_rows: List[models.Metadata],
                       cat_rows: List[models.DocumentCategory]) \
        -> domain.Document:
    """Compose a :class:`.domain.document.Document` from its classic rows.

    Shared by :func:`to_document` and :func:`to_documents_for_user` so the two
    agree; they differ only in how the rows are fetched (per paper, or in bulk
    for a user). ``rows`` are all the submissions on the paper in ascending
    ``(version, submission_id)`` order, and must include an announced one.
    """
    announced = [row for row in rows if row.is_announced()]
    latest = _latest_announced(rows)

    # `arXiv_document_category` rows are the paper's *announced* categories, so
    # everything read from them is published by definition.
    primary_clsn: Optional[domain.Classification] = None
    secondary_clsn: List[domain.Classification] = []
    for cat in cat_rows:
        clsn = domain.Classification(category=cat.category, is_published=True)
        if cat.is_primary:
            primary_clsn = clsn
        else:
            secondary_clsn.append(clsn)

    return domain.Document(
        paper_id=paper_id,
        document_id=latest.document_id,
        latest_version=latest.version,
        primary_classification=primary_clsn,
        secondary_classification=secondary_clsn,
        metadata=[_to_document_metadata(m) for m in md_rows],
        submitter_email=latest.submitter_email,
        submitter_id=latest.submitter_id,
        created=announced[0].get_created(),
        submissions=[to_submission(row) for row in rows],
    )


def load(rows: Iterable[models.Submission]) -> Optional[domain.Submission]:
    """
    Load a submission entirely from its classic database rows.

    Parameters
    ----------
    rows : list
        Items are :class:`.domain.Submission` rows loaded from the classic
        database belonging to a single arXiv e-print/submission group.

    Returns
    -------
    :class:`.domain.Submission` or ``None``
        Aggregated submission object (with ``.versions``). If there is no
        representation (e.g. all rows are deleted), returns ``None``.

    """
    versions: List[domain.Submission] = []
    submission_id: Optional[str] = None

    # We want to work within versions, and (secondarily) in order of creation
    # time.
    rows = sorted(rows, key=lambda o: o.version)
    logger.debug('Load from rows %s', [r.submission_id for r in rows])
    for version, version_rows in groupby(rows, key=attrgetter('version')):
        # Creation time isn't all that precise in the classic database, so
        # we'll use submission ID instead.
        these_version_rows = sorted([v for v in version_rows],
                                    key=lambda o: o.submission_id)
        logger.debug('Version %s: %s', version, version_rows)
        # We use the original ID to track the entire lifecycle of the
        # submission in NG.
        if version == 1:
            submission_id = str(these_version_rows[0].submission_id)
            logger.debug('Submission ID: %s', submission_id)

        # Find the creation row. There may be some false starts that have been
        # deleted, so we need to advance to the first non-deleted 'new' or
        # 'replacement' row.
        version_submission: Optional[domain.Submission] = None
        while version_submission is None:
            try:
                row = these_version_rows.pop(0)
            except IndexError:
                break
            if row.is_new_version() and \
                    (row.type == row.NEW_SUBMISSION or not row.is_deleted()):
                # Get the initial state of the version.
                version_submission = to_submission(row, submission_id)
                logger.debug('Got initial state: %s', version_submission)

        if version_submission is None:
            logger.debug('Nothing to work with for this version')
            continue

        # If this is not the first version, carry forward any requests.
        if len(versions) > 0:
            logger.debug('Bring user_requests forward from last version')
            version_submission.user_requests.update(versions[-1].user_requests)

        for row in these_version_rows:  # Remaining rows, since we popped the others.
            # We are treating JREF submissions as though there is no approval
            # process; so we can just ignore deleted JREF rows.
            if row.is_jref() and not row.is_deleted():
                # This should update doi, journal_ref, report_num.
                version_submission = patch_jref(version_submission, row)
            # For withdrawals and cross-lists, we want to get data from
            # deleted rows since we keep track of all requests in the NG
            # submission.
            elif row.is_withdrawal():
                # This should update the reason_for_withdrawal (if applied),
                # and add a WithdrawalRequest to user_requests.
                version_submission = patch_withdrawal(version_submission, row)
            elif row.is_crosslist():
                # This should update the secondary classifications (if applied)
                # and add a CrossListClassificationRequest to user_requests.
                version_submission = patch_cross(version_submission, row)

            # We want hold information represented as a Hold on the submission
            # object, not just the status.
            if version_submission and version_submission.is_on_hold:
                version_submission = patch_hold(version_submission, row)
        versions.append(version_submission)

    if not versions:
        return None
    submission = copy.deepcopy(versions[-1])
    submission.versions = [ver for ver in versions if ver and ver.is_announced]
    return submission


def announce_submission(session: SQLAlchemySession, submission_id: str) -> None:
    dbss = _get_db_submission_rows(session, submission_id)
    head = sorted([o for o in dbss if o.is_new_version()], key=lambda o: o.submission_id)[-1]
    if not head.is_announced():
        head.status = Submission.ANNOUNCED
    if head.document is None:
        paper_id = datetime.now().strftime('%s')[-4:] \
                   + "." \
                   + datetime.now().strftime('%s')[-5:]
        # `submitter_id`/`created`/`title` as legacy's publish would set them;
        # `to_documents_for_user` selects and orders papers on the first two.
        head.document = models.Document(paper_id=paper_id,
                                        title=head.title,
                                        submitter_id=head.submitter_id,
                                        submitter_email=head.submitter_email,
                                        created=datetime.now())
        head.doc_paper_id = paper_id
    session.add(head)
    session.commit()


def _get_head_idx(session: SQLAlchemySession, rows: List[Submission]) -> int:
    """bdc34: Not sure what this is"""
    raise NotImplementedError()
