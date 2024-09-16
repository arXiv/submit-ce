from typing import Dict

from fastapi import Depends

from .default_api_base import BaseDefaultApi
import logging

from .models.agreement import Agreement
from ..db import get_db

logger = logging.getLogger(__name__)


def legacy_depends(db=Depends(get_db)) -> dict:
    return {"db": db}


class LegacySubmitImplementation(BaseDefaultApi):

    async def get_submission(self, impl_data: Dict, submission_id: str) -> object:
        pass

    async def new(self, impl_data: Dict) -> str:
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