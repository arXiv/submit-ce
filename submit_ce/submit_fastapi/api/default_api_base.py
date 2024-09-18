# coding: utf-8
from abc import ABC, abstractmethod

from typing import ClassVar, Dict, List, Tuple, Union  # noqa: F401

from submit_ce.submit_fastapi.api.models.events import AgreedToPolicy, StartedNew
from submit_ce.submit_fastapi.api.models.agent import User, Client


class BaseDefaultApi(ABC):

    @abstractmethod
    async def get_submission(
            self,
            impl_data: Dict,
            user: User,
            client: Client,
            submission_id: str,
    ) -> object:
        """Get information about a ui-app."""
        ...

    @abstractmethod
    async def start(
            self,
            impl_data: Dict,
            user: User,
            client: Client,
            started: Union[StartedNew],
    ) -> str:
        """Start a ui-app and get a ui-app ID."""
        ...

    @abstractmethod
    async def accept_policy_post(
            self,
            impl_data: Dict,
            user: User,
            client: Client,
            submission_id: str,
            agreement: AgreedToPolicy,
    ) -> object:
        """Agree to an arXiv policy to initiate a new item ui-app or  a change to an existing item. """
        ...

    @abstractmethod
    async def mark_deposited_post(
            self,
            impl_data: Dict,
            user: User,
            client: Client,
            submission_id: str,
    ) -> None:
        """The submission been successfully deposited into the arxiv corpus."""
        ...

    @abstractmethod
    async def mark_processing_for_deposit_post(
            self,
            impl_data: Dict,
            user: User,
            client: Client,
            submission_id: str,
    ) -> None:
        """Mark that the ui-app is being processed for deposit."""
        ...

    @abstractmethod
    async def unmark_processing_for_deposit_post(
            self,
            impl_data: Dict,
            user: User,
            client: Client,
            submission_id: str,
    ) -> None:
        """Indicate that an external system in no longer working on depositing this ui-app.  This does not indicate that is was successfully deposited. """
        ...

    @abstractmethod
    async def get_service_status(
            self,
            impl_data: Dict,
    ) -> Tuple[bool, str]:
        """Service health."""
        ...
