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
from submit_ce.api.email_service import EmailService
from submit_ce.api.save_participant import (SaveContext, SaveFailure,
                                            SaveParticipant, SavePhase)
from submit_ce.api.file_store import SubmissionFileStore
from submit_ce.domain.agent import Client, User
from submit_ce.domain.config import SubmitConfig
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
from ...domain.exceptions import NoSuchSubmission, NothingToDo, SaveError
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
    """Implementation of `SubmitApi` that interoperates with legacy submission.

    Persists submissions and their events to the classic arXiv database and
    the submission file store (SFS), bridging the event-sourced domain model
    onto the legacy ``arXiv_submissions`` tables.

    Parameters
    ----------
    store : SubmissionFileStore
        File store used to persist and retrieve submission source packages,
        previews and related artifacts.
    compiler : CompileService
        Service used to compile submission sources (e.g. to PDF).
    email_service : EmailService
        Service used to send notification email.
    config : SubmitConfig
        Configuration thta is relevant to the SubmitAPI.
    get_session : Callable[[], SqlalchemySession], optional
        Factory returning a SQLAlchemy session for database access.
    participants : Optional[List[SaveParticipant]]
        Participants enlisted in every ``save()`` transaction. See
        :mod:`submit_ce.api.save_participant`.
    
    Notes
    -----
    TODO success response objects (similar to modapi? {msg: success, updated_fields:[]})
    TODO failure to validate response objects (which field caused the problem?)
    TODO Failure response object (general failure message)
    TODO Later: edit token similar to modapi?
    """

    def __init__(self,
                 store: SubmissionFileStore,
                 compiler: CompileService,
                 email_service: EmailService,
                 config: SubmitConfig,
                 get_session:Callable[[],SqlalchemySession],
                 participants: Optional[List[SaveParticipant]] = None):
        self.get_session = get_session
        self.compiler = compiler
        self.store = store
        self.email_service = email_service
        self.config = config or SubmitConfig()
        self.participants = list(participants or [])

    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}("
                f"store={self.store.__repr__()},"
                f"compiler={self.compiler.__repr__()},"
                f"email_service={self.email_service.__repr__()},"
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
        if isinstance(events[0], Withdraw) and len(events) > 1:
            # BDC I don't love how the Withdraw is handled. I'd perfer if it were done in a side effect
            raise SaveError("Must save Withdraw as the only item in the list of Events")
        ctx = SaveContext(api=self, submission_id=submission_id, requested_events=events)
        with self.get_session() as session:
            try:
                if isinstance(events[0], Withdraw):
                    result = self._save_withdrawal(events[0], session, ctx)
                else:
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

                        ctx.phase = SavePhase.LOAD_LOCK
                        before, existing_events = self._load(session, submission_id, lock_row=True)
                        ctx.before = before
                        ctx.existing_events = existing_events
                    elif events[0].submission_id is None and not isinstance(events[0], CreateSubmission):
                        raise NoSuchSubmission('Unable to determine submission')
                    self._participants_under_lock(ctx)
                    result = self._save(*events, submission=before, session=session,
                                        existing_events=existing_events, ctx=ctx)
            except BaseException as exc:
                # Roll back explicitly (rather than relying on the session
                # context manager) so on_rollback participants observe
                # post-rollback state. The original exception propagates
                # unchanged; participant failures are logged, never masking it.
                session.rollback()
                failure = SaveFailure(exc=exc, phase=ctx.phase,
                                      event=ctx.current_event,
                                      participant=ctx.current_participant)
                for participant in reversed(self.participants):
                    try:
                        participant.on_rollback(ctx, failure)
                    except Exception:
                        logger.exception("on_rollback failed for participant %r",
                                         participant)
                raise
        self._participants_after_commit(ctx)
        return result

    def _participants_under_lock(self, ctx: SaveContext) -> None:
        """Fire `under_lock` in participant list order, inside the transaction."""
        for participant in self.participants:
            ctx.phase = SavePhase.PARTICIPANT_UNDER_LOCK
            ctx.current_participant = participant
            participant.under_lock(ctx)
        ctx.current_participant = None

    def _participants_before_commit(self, ctx: SaveContext) -> None:
        """Fire `before_commit` in reverse list order, inside the transaction."""
        for participant in reversed(self.participants):
            ctx.phase = SavePhase.PARTICIPANT_BEFORE_COMMIT
            ctx.current_participant = participant
            participant.before_commit(ctx)
        ctx.current_participant = None

    def _participants_after_commit(self, ctx: SaveContext) -> None:
        """Fire `after_commit` in reverse list order.

        The save has already committed, so exceptions are logged and
        swallowed — they must not fail a save the caller will be told
        succeeded."""
        for participant in reversed(self.participants):
            try:
                participant.after_commit(ctx)
            except Exception:
                logger.exception("after_commit failed for participant %r",
                                 participant)

    def _save(self, *events,
              submission: Submission,
              session,
              existing_events: List[Event],
              ctx: SaveContext
              ) -> Tuple[Submission, List[Event]]:
        """Internal save for when submission is already read from the db."""
        before = submission
        committed: List[Event] = ctx.committed  # alias: participants see it grow
        # A work-queue since events may imply consequent events (see
        # Event.consequences) that need to be processed in this same locked
        # session/transaction. They are inserted at the front of the queue so a
        # consequence applies to the state immediately after its parent, before
        # any remaining sibling events. The consequence type-graph is acyclic
        # (enforced by test), so this terminates.
        queue: List[Event] = list(events)
        while queue:
            event = queue.pop(0)
            ctx.current_event = event
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
                # validate_under_lock runs inside the locked
                # transaction so it can inspect on-disk / FileStore
                # state without racing against another writer. Raising
                # InvalidEvent here rolls the DB transaction back.
                # Any earlier EventWithSideEffect.execute() is not rolled back.
                # The caller's `except InvalidEvent` decides UX.
                ctx.phase = SavePhase.EVENT_VALIDATE_UNDER_LOCK
                event.validate_under_lock(self, before)
                logger.debug('Execute event %s: %s', event.event_id, event.NAME)
                ctx.phase = SavePhase.EVENT_EXECUTE
                event.execute(self, before)
                if not event.executed:
                    event.executed = get_tzaware_utc_now()

            logger.debug('Apply event %s: %s', event.event_id, event.NAME)
            ctx.phase = SavePhase.EVENT_APPLY
            after = event.apply(before)
            if not event.committed:
                ctx.phase = SavePhase.EVENT_PERSIST
                consequent_event, after = db.store_event(session, event, before, after)
                committed.append(consequent_event)

            before = after  # Prepare for the next event.
            ctx.after = after

            # Queue any follow-on events implied by this one, given the new state.
            for consequence in reversed(event.get_consequences(after)):
                queue.insert(0, consequence)

        ctx.current_event = None
        all_ = sorted(existing_events + committed, key=lambda e: e.created)
        self._participants_before_commit(ctx)
        ctx.phase = SavePhase.COMMIT
        session.commit()
        return after, list(all_)

    def _save_withdrawal(self, event: Withdraw, session, ctx: SaveContext) \
            -> Tuple[Submission, List[Event]]:
        """Save a `Withdraw`, creating a new ``wdr`` submission.

        A withdrawal creates a brand-new submission seeded from the most recent
        announced version of ``event.paper_id``. The new row (and its id) must
        exist before ``execute()`` runs, since the withdrawn source file is
        written to the new submission's workspace.
        """
        event.created = datetime.now(UTC)
        ctx.phase = SavePhase.LOAD_LOCK
        seed = db.to_submission(db.load_latest_announced(session, event.paper_id))
        ctx.before = seed
        self._participants_under_lock(ctx)

        ctx.current_event = event
        # Creates the wdr row and assigns the new submission id onto `after`.
        ctx.phase = SavePhase.EVENT_PERSIST
        consequent, after = db.store_withdrawal(session, event, seed)

        # Now that the new id exists, write the `withdrawn` source file to it.
        ctx.phase = SavePhase.EVENT_EXECUTE
        event.execute(self, after)
        if not event.executed:
            event.executed = get_tzaware_utc_now()

        ctx.after = after
        ctx.committed.append(consequent)
        ctx.current_event = None
        self._participants_before_commit(ctx)
        ctx.phase = SavePhase.COMMIT
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
    def get_email_service(self) -> EmailService:
        return self.email_service

    @override
    def get_config(self) -> SubmitConfig:
        return self.config

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
