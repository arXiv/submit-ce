# coding: utf-8
from abc import ABC, abstractmethod
from typing import ClassVar, Dict, List, Tuple, Union  # noqa: F401

from fastapi import UploadFile

from submit_ce.fastapi.api.models import CategoryChangeResult
from submit_ce.fastapi.api.models.agent import User, Client
from submit_ce.fastapi.api.models.events import AgreedToPolicy, StartedNew, AuthorshipDirect, AuthorshipProxy, \
    SetLicense, SetCategories, SetMetadata


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

    @abstractmethod
    async def set_license_post(self, impl_dep: Dict, user: User, client: Client,
                               submission_id: str, license: SetLicense) -> None:
        """Sets the license of the submission files."""
        ...

    async def assert_authorship_post(self, impl_dep: Dict, user: User, client: Client,
                                     submission_id: str, authorship: Union[AuthorshipDirect, AuthorshipProxy]) -> str:
        """Assert authorship of the submission files.

        Or assert that the submitter has authority to submit the files as a proxy."""
        ...

    async def file_post(self, impl_dep: Dict, user: User, client: Client, submission_id: str, uploadFile: UploadFile):
        """Upload a file to a submission.

        The file can be a single file, a zip, or a tar.gz. Zip and tar.gz files will be unpacked.
        """
        ...

    async def set_categories_post(self, impl_dep: Dict, user: User, client: Client, submission_id: str,
                                  set_categoires: SetCategories) -> CategoryChangeResult:
        pass

    async def set_metadata_post(self, impl_dep: Dict, user: User, client: Client, submission_id: str,
                                metadata: Union[SetMetadata]):
        pass
