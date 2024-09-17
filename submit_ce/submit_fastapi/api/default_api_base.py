# coding: utf-8
from abc import ABC, abstractmethod

from typing import ClassVar, Dict, List, Tuple  # noqa: F401

from .models.agreement import Agreement


class BaseDefaultApi(ABC):

    @abstractmethod
    async def get_submission(
        self,
        impl_data: Dict,
        submission_id: str,
    ) -> object:
        """Get information about a ui-app."""
        ...

    @abstractmethod
    async def begin(
        self,
        impl_data: Dict,

    ) -> str:
        """Start a ui-app and get a ui-app ID."""
        ...

    @abstractmethod
    async def submission_id_accept_policy_post(
        self,
        impl_data: Dict,
        submission_id: str,
        agreement: Agreement,
    ) -> object:
        """Agree to an arXiv policy to initiate a new item ui-app or  a change to an existing item. """
        ...

    @abstractmethod
    async def submission_id_deposited_post(
        self,
        impl_data: Dict,
        submission_id: str,
    ) -> None:
        """The ui-app has been successfully deposited by an external service."""
        ...

    @abstractmethod
    async def submission_id_mark_processing_for_deposit_post(
        self,
        impl_data: Dict,
        submission_id: str,
    ) -> None:
        """Mark that the ui-app is being processed for deposit."""
        ...

    @abstractmethod
    async def submission_id_unmark_processing_for_deposit_post(
        self,
        impl_data: Dict,
        submission_id: str,
    ) -> None:
        """Indicate that an external system in no longer working on depositing this ui-app.  This does not indicate that is was successfully deposited. """
        ...
