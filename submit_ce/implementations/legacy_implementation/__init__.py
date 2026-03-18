import logging
from datetime import datetime, UTC
from typing import Optional, List, Tuple, Callable
from typing_extensions import override

from arxiv.auth.domain import User as AuthDomainUser
from arxiv.auth.legacy.endorsements import get_endorsements
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as SqlalchemySession, Session

from submit_ce.api import SubmitApi
from submit_ce.api.file_store import SubmissionFileStore
from submit_ce.domain.types import SubmitFile
from submit_ce.domain.agent import Client, User
from submit_ce.domain.meta import License
from ...api.compile_service import CompileService

from ..schedule import next_announcement_time, next_freeze_time

from .db import to_submission
from .models import Submission
from . import models
from ..file_store.legacy_file_store import LegacyFileStore

from ...domain.uploads import Workspace
from ...domain.event.base import Event, EventWithSideEffect
from ...domain.util import get_tzaware_utc_now

from ...domain.event import CreateSubmission, SetUploadPackage
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

        if store is None:
            self.store = LegacyFileStore(root_dir="data/new")  # for testing only
        else:
            self.store = store

    @override
    def get(self, submission_id: str) -> Submission:
        return self._load(self.get_session(), submission_id)[0]

    @override
    def get_with_history(self, submission_id: int) -> Tuple[Submission, List[Event]]:
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

    def _load(self, session: SqlalchemySession, submission_id: int, lock_row: bool = False) \
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
            return (to_submission(submission), [])


    @override
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
            if event.submission_id is None and submission and submission.submission_id is not None:
                event.submission_id = submission.submission_id

            # The created timestamp should be roughly when the event was committed.
            # Since the event may refer to its own ID which in future versions should be based on the
            # creation time, this must be set before the event is applied.
            event.created = datetime.now(UTC)
            if isinstance(event, EventWithSideEffect):
                if event.executed:
                    raise RuntimeError("Must not save and execute an already executed event. "
                                       "{event.event_id} {event.NAME} executed {event.executed}")
                logger.debug('Execute event %s: %s', event.event_id, event.NAME)
                event.execute(self, submission)
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
    def upload(self, file: SubmitFile, submission_id: int, user: User, client: Client) -> Workspace:
        """Saves file to legacy FS and sets the upload package on the submission."""
        if not isinstance(file, SubmitFile):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="SubmitFile Must have file, it must have a filename, content-type and steam")
        logger.debug(f"Uploaded archive MIME type: {file.content_type}.")
        if file.content_type not in acceptable_types:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f"File content type must be one of {acceptable_types} but it was {file.content_type}")

        session = self.get_session()
        check_user_authorized(session, user, client, submission_id)

        """
        This is a critical section where: 
        1. the submission is read from the db
        2. files are uploaded
        3. the file state is written to the db, checksum, size, file type.
         
        If serialize_file_operations=False the db won't be locked. If it is True, the arXiv_submission row for the 
        submission will be locked. Legacy did not lock during file upload.
        
        There are at least these problems:
        
        1. Correctness problem: If the files are uploaded, the state of the files changes, these need to be written to the db, if there
        is an exception before the db is written then the db and files are out of sync.
        
        2. Race condition problem: if the db submission row is not locked, two processes can both upload at the same time 
        which can create a file system state that neither intended.
        
        (there may be other problems)
        
        We may need a different design for this. Maybe a immutable upload space id? 
        Maybe go to no file state info in the db?  
        
        FAQ:
        What happens if the _load() locks but then there is an exception during file upload or other times? 
        The session will be rolled back by https://github.com/arXiv/arxiv-base/blob/b99d4b4a842b3077f740455f685396af71b293dd/arxiv/base/__init__.py#L127
        The files on the FS may not match what is in the db for size and checksum.
        """

        submission, event_list = self._load(session, submission_id, lock_row=self.serialize_file_operations)

        self.store.store_source_package(submission.submission_id, file, 4098)
        workspace = self.store.get_workspace(submission.submission_id, "fakeuploadid")

        command = SetUploadPackage(creator=user, client=client,
                                   submission_id=submission.submission_id,
                                   identifier=str(workspace.identifier),
                                   checksum=f"BOGUS {__file__}",
                                   uncompressed_size=workspace.size,
                                   compressed_size=workspace.compressed_size or 0,
                                   source_format=workspace.source_format,
                                   )
        command.validate(submission)
        self._save(command, submission=submission, session=session, existing_events=event_list)
        session.commit()  # unlocks submission row
        return workspace

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
