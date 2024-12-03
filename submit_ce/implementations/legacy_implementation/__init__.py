import logging
from datetime import datetime, UTC
from typing import Optional, List, Tuple, Callable

from arxiv.auth.domain import User as AuthDomainUser
from arxiv.auth.legacy.endorsements import get_endorsements
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as SqlalchemySession, Session

from submit_ce.api import domain as api, SubmitApi, Event, License, SubmitFile, Agent, Client, Upload
from submit_ce.api.file_store import SubmissionFileStore
from submit_ce.implementations.file_store.legacy_file_store import LegacyFileStore
from .db import to_submission
from .models import Submission, Document, SubmissionCategory
from ...api.domain.event import CreateSubmission
from ...api.exceptions import NoSuchSubmission, NothingToDo
from . import db

logger = logging.getLogger(__name__)


def check_user_authorized(session: Session, user: api.User, client: api.Client, submision_id: str) -> None:
    # TODO implement authorized check, use scopes from arxiv.auth?
    # TODO implement is_locked on submission
    pass


class LegacySubmitImplementation(SubmitApi):
    """
    Implementation of `SubmitApi` that interoperates with legacy submission by writing to SFS and DB.

    TODO write admin log on all changes
    TODO success response objects (similar to modapi? {msg: success, updated_fields:[]})
    TODO failure to validate response objects (which field caused the problem?)
    TODO Failure response object (general failure message)
    TODO Later: edit token similar to modapi?
    """

    def __init__(self,
                 store: Optional[SubmissionFileStore] = None,
                 get_session:Callable[[],SqlalchemySession] = None,
                 get_user: Callable[[],api.User] = None,
                 get_client: Callable[[], api.Client] = None,
                 serialize_file_operations:bool = False):
        self.get_user = get_user
        self.get_client = get_client
        self.get_session = get_session
        self.serialize_file_operations = serialize_file_operations

        if store is None:
            self.store = LegacyFileStore(root_dir="data/new")  # for testing only
        else:
            self.store = store

    def load(self, submission_id: str) -> Tuple[Submission, List[Event]]:
        return self._load(self.get_session(), submission_id)

    def _load(self, session: SqlalchemySession, submission_id: str, lock_row: bool = False) -> Tuple[Submission, List[Event]]:
        if not submission_id:
            raise NoSuchSubmission()
        if isinstance(submission_id, str) and not submission_id.isdigit():
            raise NoSuchSubmission(f"Submission {submission_id[0:20]} does not exist (legacy must use int ids)")
        stmt = select(Submission).where(Submission.submission_id == int(submission_id))
        if lock_row:  # row will be locked until .commit() use .flush() to get auto inc ids without unlocking
            stmt = stmt.with_for_update()
        submission = session.scalars(stmt).first()
        if not submission:
            raise NoSuchSubmission()
        else:
            return (to_submission(submission), [])

    def load_submissions_for_user(self, user_id: str) -> List[Submission]:
        session = self.get_session()
        stmt = select(models.Submission) \
            .where(models.Submission.submitter_id == int(user_id),
                   models.Submission.status.in_([0, 1, 2, 4])) \
            .order_by(Submission.submission_id.desc())
        submissions: List[Submission] = [to_submission(row) for row in session.execute(stmt).unique().scalars().all()]
        return submissions

    def save(self, *events: Event, submission_id: Optional[int] = None) -> Tuple[Submission, List[Event]]:
        if not events:
            raise NothingToDo()
        with self.get_session() as session:
            before: Optional[Submission] = None
            existing_events: List[Event] = []
            if submission_id is not None:
                before, existing_events = self._load(session, submission_id, lock_row=True)
            elif events[0].submission_id is None and not isinstance(events[0], CreateSubmission):
                raise NoSuchSubmission('Unable to determine submission')

            committed: List[Event] = []
            for event in events:
                if event.submission_id is None and submission_id is not None:
                    event.submission_id = submission_id

                # The created timestamp should be roughly when the event was committed.
                # Since the event may refer to its own ID which in future versions should be based on the
                # creation time, this must be set before the event is applied.
                event.created = datetime.now(UTC)
                logger.debug('Apply event %s: %s', event.event_id, event.NAME)
                after = event.apply(before)
                if not event.committed:
                    consequent_event, after =db.store_event(session, event, before, after)
                    committed.append(consequent_event)

                before = after  # Prepare for the next event.

            all_ = sorted(existing_events + committed, key=lambda e: e.created)
            session.commit()
            return after, list(all_)

    def get_service_status(self, impl_data: dict):
        return f"{self.__class__.__name__}  impl_data: {impl_data}"

    def licenses(self, active_only=True) -> List[License]:
        with self.get_session() as session:
            return db.get_licenses(session, active_only=active_only)


    def categories_for_user(self, user_id: str) -> Optional[str]:
        return get_endorsements(AuthDomainUser(user_id=user_id) )

    def upload(self, file: SubmitFile, submission_id: int, user: Agent, client: Client) -> Upload:
        """Saves file to legacy FS and sets the upload package on the submission."""
        session = self.get_session()
        check_user_authorized(session, user, client, submission_id)
        submission, event_list = self._load(session, submission_id, lock_row=self.serialize_file_operations)
        acceptable_types = ["application/gzip", "application/tar", "application/tar+gzip"]
        if file.content_type not in acceptable_types:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="File content type must be one of {acceptable_types}")

        self.store.store_source_package(submission.submission_id, file)
        return self.store.get_workspace(submission.submission_id, "fakeuploadid")
        # TODO db changes for upload: source_format
        # TODO db changes for upload: source_size
        # TODO db changes for upload: package?


