from typing import Dict

from fastapi import Depends

from submit_ce.submit_fastapi.api.default_api_base import BaseDefaultApi
import logging

from submit_ce.submit_fastapi.api.models.agreement import Agreement
from submit_ce.submit_fastapi.config import Settings
from submit_ce.submit_fastapi.db import get_db, get_sessionlocal
from submit_ce.submit_fastapi.implementations import ImplementationConfig

logger = logging.getLogger(__name__)


def legacy_depends(db=Depends(get_db)) -> dict:
    return {"db": db}


class LegacySubmitImplementation(BaseDefaultApi):

    async def get_submission(self, impl_data: Dict, submission_id: str) -> object:
        pass

    async def begin(self, impl_data: Dict) -> str:
        pass

    async def submission_id_accept_policy_post(self, impl_data: Dict, submission_id: str,
                                               agreement: Agreement) -> object:
        pass

    async def submission_id_deposited_post(self, impl_data: Dict, submission_id: str) -> None:
        pass

    async def submission_id_mark_processing_for_deposit_post(self, impl_data: Dict, submission_id: str) -> None:
        pass

    async def submission_id_unmark_processing_for_deposit_post(self, impl_data: Dict, submission_id: str) -> None:
        pass

    async def get_service_status(self, impl_data: dict):
        return f"{self.__class__.__name__}  impl_data: {impl_data}"


def setup(settings: Settings) -> None:
    pass

def legacy_bootstrap(settings: Settings) -> None:
    sessionlocal = get_sessionlocal()
    with sessionlocal() as session:
        import arxiv.db.models as models
        models.configure_db_engine(session.get_bind())
        session.create_all()

implementation = ImplementationConfig(
    impl=LegacySubmitImplementation(),
    depends_fn=legacy_depends,
    setup_fn=setup,
)