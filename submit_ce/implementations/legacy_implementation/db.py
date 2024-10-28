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
from _operator import attrgetter
from datetime import datetime
from functools import wraps
from itertools import groupby
from operator import attrgetter
from typing import List, Optional, Tuple, Callable, Any, TypeVar, cast, Iterable
import logging

from arxiv.license import LICENSES
from pydantic import RootModel
from retry import retry as _retry
from sqlalchemy import or_
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session as SQLAlchemySession
from sqlalchemy.orm.exc import NoResultFound

from . import models, interpolate, log
from .models import DBEvent
from .patch import patch_hold, patch_withdrawal, patch_cross, patch_jref
from ...api import domain
from ...api.domain import Event, Submission, Agent, User, WithdrawalRequest, CrossListClassificationRequest, Client
from ...api.domain import License
from ...api.domain.event import SetJournalReference, SetDOI, SetReportNumber, CreateSubmission, Rollback, \
    RequestWithdrawal, RequestCrossList, CancelRequest
from ...api.exceptions import NoSuchSubmission

logger = logging.getLogger(__name__)
logger.propagate = False

JREFEvents = [SetDOI, SetJournalReference, SetReportNumber]

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
            raise OperationalError('Classic database unavailable') from e
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
def get_events(session: SQLAlchemySession, submission_id: int) -> List[Event]:
    """
    Load events from the classic database.

    Parameters
    ----------
    submission_id : int

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
    if not events:      # No events, no dice.
        logger.error('No events for submission %s', submission_id)
        raise NoSuchSubmission(f'Submission {submission_id} not found')
    return events


# @retry(ClassicBaseException, tries=3, delay=1)
@handle_operational_errors
def get_submission(session: SQLAlchemySession, submission_id: int, for_update: bool = False) \
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
    submission_id : int

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

        if for_update:      # Lock these rows as well.
            subsequent_query = subsequent_query.with_for_update(read=True)
        subsequent_rows = list(subsequent_query)   # Execute query.
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
def store_event(session: SQLAlchemySession, event: Event, before: Optional[Submission], after: Submission,
                *call: Callable) -> Tuple[Event, Submission]:
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
    event : :class:`Event`
    before : :class:`Submission`
        The state of the submission before the event occurred.
    after : :class:`Submission`
        The state of the submission after the event occurred.
    call : list
        Items are callables that accept args ``Event, Submission, Submission``.
        These are called within the transaction context; if an exception is
        raised, the transaction is rolled back.

    """
    # Let the caller determine the transaction scope.
    if event.committed:
        raise ValueError(f'{event.event_type} {event.event_id} already committed')
    if event.created is None:
        raise ValueError('Event creation timestamp not set')
    logger.debug('store event %s', event.event_type)

    doc_id: Optional[int] = None

    # This is the case that we have a new submission.
    if before is None:    # and isinstance(after, Submission):
        dbs = models.Submission(type=models.Submission.NEW_SUBMISSION)
        dbs.update_from_submission(after)
        this_is_a_new_submission = True

    else:   # Otherwise we're making an update for an existing submission.
        this_is_a_new_submission = False

        if before.arxiv_id is not None: #:
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
            elif isinstance(event, RequestCrossList):
                dbs = _create_crosslist(doc_id, event.categories,
                                        before.arxiv_id, after.version, after,
                                        event.created)

            # Adding DOIs and citation information (so-called "journal reference")
            # also requires a new row. The version number is not incremented.
            elif before.is_announced and type(event) in JREFEvents:
                dbs = _create_jref(session, doc_id, before.arxiv_id, after.version, after,
                                event.created)

            elif isinstance(event, CancelRequest):
                dbs = _cancel_request(session, event, before, after)

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

    session.add(dbs)
    session.flush()

    # TODO Event storage disabled
    # Attach the database object for the event to the row for the
    #  submission.
    # if this_is_a_new_submission:    # Update in transaction.
    #     db_event.submission = dbs
    # else:                           # Just set the ID directly.
    #     assert before is not None
    #     db_event.submission_id = before.submission_id
    #db_event = _new_dbevent(event)
    #session.add(db_event)

    # Make sure that we get a submission ID; note that this # does not commit
    # the transaction, just pushes the # SQL that we have generated so far to
    # the database # server.

    log.handle(event, before, after)   # Create admin log entry.
    for func in call:
        logger.debug('call %s with event %s', func, event.event_id)
        func(event, before, after)

    event.committed = True

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
    return event, after


def _load(session: SQLAlchemySession,
          submission_id: Optional[int] = None, paper_id: Optional[str] = None,
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
    logger.debug('get document ID with %s and %s', paper_id, version)
    document_id = session.query(models.Submission.document_id) \
        .filter(models.Submission.doc_paper_id == paper_id) \
        .filter(models.Submission.version == version) \
        .first()
    if document_id is None:
        raise NoSuchSubmission("No submission row matches those parameters")
    return int(document_id[0])


def _create_replacement(document_id: int, paper_id: str, version: int,
                        submission: Submission, created: datetime) \
        -> models.Submission:
    """
    Create a new replacement submission.

    From the perspective of the database, a replacement is mainly an
    incremented version number. This requires a new row in the database.
    """
    dbs = models.Submission(type=models.Submission.REPLACEMENT,
                            document_id=document_id, version=version)
    dbs.update_from_submission(submission)
    dbs.created = created
    dbs.updated = created
    dbs.doc_paper_id = paper_id
    dbs.status = models.Submission.NOT_SUBMITTED
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
                            version=version)
    dbs.update_withdrawal(submission, reason, paper_id, version, created)
    return dbs


def _create_crosslist(document_id: int, categories: List[str], paper_id: str,
                      version: int, submission: Submission,
                      created: datetime) -> models.Submission:
    """
    Create a new crosslist request.

    Cross list requests also require a new row, and they use the most recent
    version number.
    """
    dbs = models.Submission(type=models.Submission.CROSS_LIST,
                            document_id=document_id,
                            version=version)
    dbs.update_cross(submission, categories, paper_id, version, created)
    return dbs


def _create_jref(session: SQLAlchemySession, document_id: int, paper_id: str, version: int,
                 submission: Submission,
                 created: datetime) -> models.Submission:
    """
    Create a JREF submission.

    Adding DOIs and citation information (so-called "journal reference") also
    requires a new row. The version number is not incremented.
    """
    # Try to piggyback on an existing JREF row. In the classic system, all
    # three fields can get updated on the same row.
    try:
        most_recent_sb = _load(session, paper_id=paper_id, version=version,
                               row_type=models.Submission.JOURNAL_REFERENCE)
        if most_recent_sb and not most_recent_sb.is_announced():
            most_recent_sb.update_from_submission(submission)
            return most_recent_sb
    except NoSuchSubmission:
        pass

    # Otherwise, create a new JREF row.
    dbs = models.Submission(type=models.Submission.JOURNAL_REFERENCE,
                            document_id=document_id, version=version)
    dbs.update_from_submission(submission)
    dbs.created = created
    dbs.updated = created
    dbs.doc_paper_id = paper_id
    dbs.status = models.Submission.PROCESSING_SUBMISSION
    return dbs


def _new_dbevent(event: Event) -> DBEvent:
    """Create an event entry in the database."""
    return DBEvent(event_type=event.event_type,
                   event_id=event.event_id,
                   event_version=_get_app_version(),
                   data=event.model_dump_json().encode('utf-8'),
                   created=event.created,
                   creator=RootModel[Agent](event.creator).model_dump_json().encode('utf-8'),
                   proxy=RootModel[Agent](event.proxy).model_dump_json().encode('utf-8') if event.proxy else None)


def _preserve_sticky_hold(dbs: models.Submission, before: Submission,
                          after: Submission, event: Event) -> None:
    if dbs.status != models.Submission.ON_HOLD:
        return
    if dbs.is_on_hold() and after.status == Submission.WORKING:
        dbs.sticky_status = models.Submission.ON_HOLD


def _get_app_version() -> str:
    return '0.0.0'


def _get_db_submission_rows(session: SQLAlchemySession, submission_id: int) -> List[models.Submission]:
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
                  submission_id: Optional[int] = None) -> domain.Submission:
    """
    Generate a representation of submission state from a DB instance.

    Parameters
    ----------
    row : :class:`.domain.Submission`
        Database row representing a :class:`.domain.submission.Submission`.
    submission_id : int or None
        If provided the database value is overridden when setting
        :attr:`domain.Submission.submission_id`.

    Returns
    -------
    :class:`.domain.submission.Submission`

    """

    status = row.status_from_classic()
    primary = row.primary_classification
    if row.submitter is None:
        submitter = domain.User(identifier=row.submitter_id,
                                email=row.submitter_email)
    else:
        submitter = row.get_submitter()
    if submission_id is None:
        submission_id = row.submission_id

    client = Client(native_id="bogus_built_from_submission_row",
                    hostname = row.remote_host)
    client.remote_addr = row.remote_addr

    license: Optional[domain.License] = None
    if row.license:
        label = LICENSES[row.license]['label']
        license = domain.License(uri=row.license, name=label)

    primary_clsn: Optional[domain.Classification] = None
    if primary and primary.category:
        primary_clsn = domain.Classification(category=primary.category)
    secondary_clsn = [
        domain.Classification(category=db_cat.category)
        for db_cat in row.categories if not db_cat.is_primary
    ]

    content: Optional[domain.SubmissionContent] = None
    if row.package:
        if row.package.startswith('fm://'):
            identifier, checksum = row.package.split('://', 1)[1].split('@', 1)
        else:
            identifier = row.package
            checksum = ""
        source_format = domain.SubmissionContent.Format(row.source_format)
        content = domain.SubmissionContent(identifier=identifier,
                                           compressed_size=0,
                                           uncompressed_size=row.source_size,
                                           checksum=checksum,
                                           source_format=source_format)

    assert status is not None
    submission = domain.Submission(
        submission_id=submission_id,
        creator=submitter,
        owner=submitter,
        client=client,
        status=status,
        created=row.get_created(),
        updated=row.get_updated(),
        source_content=content,
        submitter_is_author=bool(row.is_author),
        submitter_accepts_policy=bool(row.agree_policy),
        submitter_contact_verified=bool(row.userinfo),
        is_source_processed=not bool(row.must_process),
        submitter_confirmed_preview=bool(row.viewed),
        metadata=domain.SubmissionMetadata(title=row.title,
                                           abstract=row.abstract,
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
        version=row.version
    )
    if row.sticky_status == row.ON_HOLD or row.status == row.ON_HOLD:
        submission = patch_hold(submission, row)
    elif row.is_withdrawal():
        submission = patch_withdrawal(submission, row)
    elif row.is_crosslist():
        submission = patch_cross(submission, row)
    return submission


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
    submission_id: Optional[int] = None

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
            submission_id = these_version_rows[0].submission_id
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
            if version_submission.is_on_hold:
                version_submission = patch_hold(version_submission, row)
        versions.append(version_submission)

    if not versions:
        return None
    submission = copy.deepcopy(versions[-1])
    submission.versions = [ver for ver in versions if ver and ver.is_announced]
    return submission


def announce_submission(session: SQLAlchemySession, submission_id: int) -> None:
    dbss = _get_db_submission_rows(session, submission_id)
    head = sorted([o for o in dbss if o.is_new_version()], key=lambda o: o.submission_id)[-1]
    if not head.is_announced():
        head.status = Submission.ANNOUNCED
    if head.document is None:
        paper_id = datetime.now().strftime('%s')[-4:] \
            + "." \
            + datetime.now().strftime('%s')[-5:]
        head.document = models.Document(paper_id=paper_id)
        head.doc_paper_id = paper_id
    session.add(head)
    session.commit()


def _get_head_idx(session: SQLAlchemySession, rows: List[Submission]) -> int:
    """bdc34: Not sure what this is"""
    raise NotImplementedError()

def place_on_hold(session: SQLAlchemySession, submission_id: int) -> None:
    """WARNING WARNING WARNING this is for testing purposes only."""
    dbss = _get_db_submission_rows(session, submission_id)
    i = _get_head_idx(dbss)
    head = dbss[i]
    if head.is_announced() or head.is_on_hold():
        return
    head.status = Submission.ON_HOLD
    session.add(head)
    session.commit()

def apply_cross(session: SQLAlchemySession, submission_id: int) -> None:
    """WARNING WARNING WARNING this is for testing purposes only."""

    dbss = _get_db_submission_rows(session, submission_id)
    i = _get_head_idx(dbss)
    for dbs in dbss[:i]:
        if dbs.is_crosslist():
            dbs.status = Submission.ANNOUNCED
            session.add(dbs)
            session.commit()


def reject_cross(session: SQLAlchemySession, submission_id: int) -> None:
    """WARNING WARNING WARNING this is for testing purposes only."""

    dbss = _get_db_submission_rows(submission_id)
    i = _get_head_idx(dbss)
    for dbs in dbss[:i]:
        if dbs.is_crosslist():
            dbs.status = Submission.REMOVED
            session.add(dbs)
            session.commit()


def apply_withdrawal(session: SQLAlchemySession, submission_id: int) -> None:
    """WARNING WARNING WARNING this is for testing purposes only."""

    dbss = _get_db_submission_rows(submission_id)
    i = _get_head_idx(dbss)
    for dbs in dbss[:i]:
        if dbs.is_withdrawal():
            dbs.status = Submission.ANNOUNCED
            session.add(dbs)
            session.commit()


def reject_withdrawal(session: SQLAlchemySession, submission_id: int) -> None:
    """WARNING WARNING WARNING this is for testing purposes only."""

    dbss = _get_db_submission_rows(submission_id)
    i = _get_head_idx(dbss)
    for dbs in dbss[:i]:
        if dbs.is_withdrawal():
            dbs.status = Submission.REMOVED
            session.add(dbs)
            session.commit()

