import logging
from typing import Dict

from arxiv.config import settings
from fastapi import Depends
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from submit_ce.domain.agent import Agent
from submit_ce.submit_fastapi.api.default_api_base import BaseDefaultApi
from submit_ce.submit_fastapi.api.models.agreement import Agreement
from submit_ce.submit_fastapi.config import Settings
from submit_ce.submit_fastapi.implementations import ImplementationConfig

logger = logging.getLogger(__name__)

_sessionLocal = sessionmaker(autocommit=False, autoflush=False)


def get_sessionlocal():
    global _sessionLocal
    if _sessionLocal is None:
        if 'sqlite' in settings.CLASSIC_DB_URI:
            args = {"check_same_thread": False}
        else:
            args = {}
        engine = create_engine(settings.CLASSIC_DB_URI, echo=settings.ECHO_SQL, connect_args=args)
        _sessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    return _sessionLocal

def get_db(session_local=Depends(get_sessionlocal)):
    """Dependency for fastapi routes"""
    with session_local() as session:
        try:
            yield session
            if session.begin or session.dirty or session.deleted:
                session.commit()
        except Exception:
            session.rollback()
            raise


def legacy_depends(db=Depends(get_db)) -> dict:
    return {"db": db}


class LegacySubmitImplementation(BaseDefaultApi):

    async def get_submission(self, impl_data: Dict, user: Agent, submission_id: str) -> object:
        pass

    async def begin(self, impl_data: Dict, user: Agent) -> str:
        return "bogus_id"

    async def submission_id_accept_policy_post(self, impl_data: Dict, user: Agent,
                                               submission_id: str,
                                               agreement: Agreement) -> object:
        pass

    async def submission_id_deposited_post(self, impl_data: Dict, user: Agent, submission_id: str) -> None:
        pass

    async def submission_id_mark_processing_for_deposit_post(self, impl_data: Dict, user: Agent, submission_id: str) -> None:
        pass

    async def submission_id_unmark_processing_for_deposit_post(self, impl_data: Dict, user: Agent, submission_id: str) -> None:
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

