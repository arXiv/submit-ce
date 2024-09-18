import datetime
import logging
from typing import Dict, Union

from arxiv.config import settings
import arxiv.db
from arxiv.db.models import Submission, Document, configure_db_engine
from fastapi import Depends, HTTPException, status
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, Session as SqlalchemySession, Session

from submit_ce.submit_fastapi.api.models.agent import User, Client
from submit_ce.submit_fastapi.api.default_api_base import BaseDefaultApi
from submit_ce.submit_fastapi.api.models.events import AgreedToPolicy, StartedNew, StartedAlterExising
from submit_ce.submit_fastapi.config import Settings
from submit_ce.submit_fastapi.implementations import ImplementationConfig

logger = logging.getLogger(__name__)

_setup = False

def get_session():
    """Dependency for fastapi routes"""
    global _setup
    if not _setup:
        if 'sqlite' in settings.CLASSIC_DB_URI:
            args = {"check_same_thread": False}
        else:
            args = {}
        engine = create_engine(settings.CLASSIC_DB_URI, echo=settings.ECHO_SQL, connect_args=args)
        arxiv.db.session_factory = sessionmaker(autoflush=False, bind=engine)
        configure_db_engine(engine, None)

    with arxiv.db.session_factory() as session:
        try:
            yield session
            if session.begin or session.dirty or session.deleted:
                session.commit()
                session.close()
        except Exception:
            session.rollback()
            session.close()
            raise


def legacy_depends(db=Depends(get_session)) -> dict:
    return {"session": db}

def check_user_authorized(session: Session, user: User, client: Client, submision_id: str) -> None:
    pass # TODO implement authorized check, use scopes from arxiv.auth?

def check_submission_exists(session: Session, submission_id: str) -> Submission:
    try:
        stmt = select(Submission).where(Submission.submission_id == int(submission_id))
        submission = session.scalars(stmt).first()
        if not submission:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail=f"Submission {submission_id} does not exist")
        else:
            return submission
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Submission {submission_id} does not exist (legacy must use int ids)")


class LegacySubmitImplementation(BaseDefaultApi):

    async def get_submission(self, impl_data: Dict, user: User, client: Client, submission_id: str) -> object:
        session = impl_data["session"]
        submission = check_submission_exists(session, submission_id)
        return {c.name: getattr(submission, c.name) for c in Submission.__table__.columns}

    async def start(self, impl_data: Dict, user: User, client: Client, started: Union[StartedNew, StartedAlterExising]) -> str:
        session = impl_data["session"]
        now = datetime.datetime.utcnow()
        submission = Submission(submitter_id=user.identifier,
                                submitter_name=user.get_name(),
                                userinfo=0,
                                agree_policy=0,
                                viewed=0,
                                stage=0,
                                created=now,
                                updated=now,
                                source_size=0,
                                allow_tex_produced=0,
                                is_oversize=0,
                                auto_hold=0,
                                remote_addr=client.remoteAddress,
                                remote_host=client.remoteHost,
                                type=started.submission_type,
                                package="",
                                )
        if isinstance(started, StartedAlterExising):
            doc = session.scalars(select(Document).where(paper_id=started.paperid)).first()
            if not doc:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,detail="Existing paper not found.")
            elif doc.submitter_id != user.identifier:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="Not submitter of existing paper.")
            else:
                submission.document_id = doc.document_id
                submission.doc_paper_id = doc.paper_id

        session.add(submission)
        session.commit()
        return str(submission.submission_id)

    async def accept_policy_post(self, impl_data: Dict, user: User, client: Client,
                                 submission_id: str,
                                 agreement: AgreedToPolicy) -> object:
        session = impl_data["session"]
        submission = check_submission_exists(session, submission_id)
        if agreement.accepted_policy_id != 3:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f"policy {agreement.accepted_policy_id} is not the currently accepted policy.")
        if submission.agree_policy == 1:
            return
        submission.agreement_id = agreement.accepted_policy_id
        submission.agree_policy = 1
        session.commit()

    async def mark_deposited_post(self, impl_data: Dict, user: User, client: Client, submission_id: str) -> None:
        pass

    async def mark_processing_for_deposit_post(self, impl_data: Dict, user: User, client: Client, submission_id: str) -> None:
        pass

    async def unmark_processing_for_deposit_post(self, impl_data: Dict, user: User, client: Client, submission_id: str) -> None:
        pass

    async def get_service_status(self, impl_data: dict):
        return f"{self.__class__.__name__}  impl_data: {impl_data}"


def setup(settings: Settings) -> None:
    pass


implementation = ImplementationConfig(
    impl=LegacySubmitImplementation(),
    depends_fn=legacy_depends,
    setup_fn=setup,
)

