import logging
from datetime import datetime, UTC
from typing import Optional, List, Tuple, Callable
from sqlalchemy.exc import OperationalError, ProgrammingError
from typing_extensions import override

from arxiv.auth.domain import User as AuthDomainUser
from arxiv.auth.legacy.endorsements import get_endorsements
from sqlalchemy import select, text
from sqlalchemy.orm import Session as SqlalchemySession, Session

from submit_ce.api import SubmitApi
from submit_ce.api.file_store import SubmissionFileStore
from submit_ce.domain.agent import Client, User
from submit_ce.domain.meta import License
from ...api.compile_service import CompileService

from ..schedule import next_announcement_time, next_freeze_time

from .db import to_submission
from .models import Submission
from . import models

from ...domain.event.base import Event, EventWithSideEffect
from ...domain.util import get_tzaware_utc_now

from ...domain.event import CreateSubmission
from ...domain.event.legacy import Withdraw
from ...domain.exceptions import NoSuchSubmission, NothingToDo
from . import db


logger = logging.getLogger(__name__)


acceptable_types = ["application/x-gzip", "application/gzip", "application/tar",
                    "application/x-tar", "application/tar+gzip", "application/pdf"]


def check_user_authorized(
    session: Session, user: User, client: Client, submission_id: str
) -> None:
    # TODO implement authorized check, use scopes from arxiv.auth?
    # TODO implement is_locked on submission
    pass


class LegacySubmitImplementation(SubmitApi):
    """
    Implementation of `SubmitApi` that interoperates with legacy submission by writing to SFS and DB.

    TODO success response objects (similar to modapi? {msg: success, updated_fields:[]})
    TODO failure to validate response objects (which field caused the problem?)
    TODO Failure response object (general failure message)
    TODO Later: edit token similar to modapi?
    """

    def __init__(self,
                 store: SubmissionFileStore,
                 compiler: CompileService,
                 get_session:Callable[[],SqlalchemySession] = None,
                 serialize_file_operations:bool = False):
        self.get_session = get_session
        self.serialize_file_operations = serialize_file_operations
        self.compiler = compiler
        self.store = store

    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}("
                f"store={self.store.__repr__()},"
                f"compiler={self.compiler.__repr__()},"
                f"serialize_file_operations={self.serialize_file_operations}"
                ")")


    @override
    def get(self, submission_id: str) -> Submission:
        return self._load(self.get_session(), submission_id)[0]

    @override
    def get_with_history(self, submission_id: str) -> Tuple[Submission, List[Event]]:
        return self._load(self.get_session(), submission_id)

    @override
    def load_submissions_for_user(self, user_id: str) -> List[Submission]:
        session = self.get_session()
        stmt = select(models.Submission) \
            .where(models.Submission.submitter_id == int(user_id),
                   models.Submission.status.in_([0, 1, 2, 4])) \
            .order_by(Submission.submission_id.desc())
        return [to_submission(row) for row in
                session.execute(stmt).unique().scalars().all()]

    def _load(self, session: SqlalchemySession, submission_id: str, lock_row: bool = False) \
            -> Tuple[Submission, List[Event]]:
        if not submission_id:
            raise NoSuchSubmission()
        if isinstance(submission_id, str) and not submission_id.isdigit():
            raise NoSuchSubmission(f"Submission {submission_id[0:20]} does not exist (legacy must use int ids)")
        stmt = select(Submission).where(Submission.submission_id == int(submission_id))
        if lock_row:  # row will be locked until .commit() or use .flush() to get auto inc ids without unlocking
            stmt = stmt.with_for_update()
        submission = session.scalars(stmt).first()
        if not submission:
            raise NoSuchSubmission()
        else:
            return (to_submission(submission), db.get_events(session, submission_id))


    @override
    def save(self, *events: Event, submission_id: Optional[str] = None) -> Tuple[Submission, List[Event]]:
        if not events:
            raise NothingToDo()
        if isinstance(events[0], Withdraw):
            with self.get_session() as session:
                return self._save_withdrawal(events[0], session)
        with self.get_session() as session:
            before: Optional[Submission] = None
            existing_events: List[Event] = []
            if submission_id is not None:
                """
                This is a critical section where:
                1. the submission is read from the db
                2. changes are made to submission including file changes via Event.execute
                3. the file state is written to the db, checksum, size, file type.

                The arXiv_submission row for the submission will be
                locked. Legacy did not lock during file upload.

                There are at least these problems:

                1. Correctness problem: If the files are uploaded, the state of
                the files changes, these need to be written to the db, if there
                is an exception before the db is written then the db and files
                are out of sync.

                2. Race condition problem: if the db submission row is not
                locked, two processes can both upload at the same time which can
                create a file system state that neither intended.

                (there may be other problems)

                We may need a different design for this. Maybe a immutable
                upload space id?  Maybe go to no file state info in the db?

                FAQ:

                What happens if the _load() locks but then there is an exception
                during file upload or other times?

                The session will be rolled back and the files on the FS may not
                match what is in the db for size and checksum.  """

                before, existing_events = self._load(session, submission_id, lock_row=True)
            elif events[0].submission_id is None and not isinstance(events[0], CreateSubmission):
                raise NoSuchSubmission('Unable to determine submission')
            return self._save(*events, submission=before, session=session, existing_events=existing_events)

    def _save(self, *events,
              submission: Submission,
              session,
              existing_events: List[Event]
              ) -> Tuple[Submission, List[Event]]:
        """Internal save for when submission is already read from the db."""
        before = submission
        committed: List[Event] = []
        for event in events:
            if event.submission_id is None and before and before.submission_id is not None:
                event.submission_id = before.submission_id

            # The created timestamp should be roughly when the event was committed.
            # Since the event may refer to its own ID which in future versions should be based on the
            # creation time, this must be set before the event is applied.
            event.created = datetime.now(UTC)
            if isinstance(event, EventWithSideEffect):
                if event.executed:
                    raise RuntimeError("Must not save and execute an already executed event. "
                                       "{event.event_id} {event.NAME} executed {event.executed}")
                logger.debug('Execute event %s: %s', event.event_id, event.NAME)
                event.execute(self, before)
                if not event.executed:
                    event.executed = get_tzaware_utc_now()

            logger.debug('Apply event %s: %s', event.event_id, event.NAME)
            after = event.apply(before)
            if not event.committed:
                consequent_event, after = db.store_event(session, event, before, after)
                committed.append(consequent_event)

            before = after  # Prepare for the next event.

        all_ = sorted(existing_events + committed, key=lambda e: e.created)
        session.commit()
        return after, list(all_)

    def _save_withdrawal(self, event: Withdraw, session) \
            -> Tuple[Submission, List[Event]]:
        """Save a `Withdraw`, creating a new ``wdr`` submission.

        A withdrawal creates a brand-new submission seeded from the most recent
        announced version of ``event.paper_id``. The new row (and its id) must
        exist before ``execute()`` runs, since the withdrawn source file is
        written to the new submission's workspace.
        """
        event.created = datetime.now(UTC)
        seed = db.to_submission(db.load_latest_announced(session, event.paper_id))

        # Creates the wdr row and assigns the new submission id onto `after`.
        consequent, after = db.store_withdrawal(session, event, seed)

        # Now that the new id exists, write the `withdrawn` source file to it.
        event.execute(self, after)
        if not event.executed:
            event.executed = get_tzaware_utc_now()

        session.commit()
        return after, [consequent]

    @override
    def get_service_status(self, impl_data: dict):
        return f"{self.__class__.__name__}  impl_data: {impl_data}"
    
    @override
    def licenses(self, active_only=True) -> List[License]:
        with self.get_session() as session:
            return db.get_licenses(session, active_only=active_only)

    @override
    def categories_for_user(self, user_id: int) -> Optional[str]:
        # TODO need better way to get endorsements since they are not on JWT anymore
        uzr=AuthDomainUser(user_id=user_id,
                       email="fake@fake.com",
                       username=f"fake_username_{__file__}")
        return get_endorsements(uzr)

    @override
    def get_file_store(self) -> SubmissionFileStore:
        return self.store

    @override
    def get_compiler(self) -> CompileService:
        return self.compiler

    @override
    def next_announcement_time(self, reference: Optional[datetime] = None) -> datetime:
        return next_announcement_time(reference)

    @override
    def next_freeze_time(self, reference: Optional[datetime] = None) -> datetime:
        return next_freeze_time(reference)

    @override
    def healthy(self) -> tuple[bool, str]:
        msgs = []
        healthy = True
        try:
            session = self.get_session()
            session.execute(text("SELECT 1")).fetchone()
            msgs.append("main api db healthy")
        except (OperationalError, ProgrammingError) as e:
            logger.error(f"DB connection failed due to {e}")
            healthy=False
            msgs.append("Main api DB opertional error")
        except Exception as e:
            logger.error(f"Unexpected error while testing db connection: {e}")
            healthy=False
            msgs.append("Main api DB failed unexpectedly")

        if not self.get_compiler().is_available():
            healthy = False
            msgs.append("Compiler unhealthy")
        else:
            msgs.append("Compiler healthy")

        if not self.get_file_store().is_available():
            healthy = False
            msgs.append("File store unhealthy")
        else:
            msgs.append("File store healthy")

        return healthy, ", ".join(msgs)
