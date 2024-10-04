"""
The API Paths for submit.

NOTE: changes to path tags change the package names in the generated API
"""

from typing import Dict, List, Callable, Annotated, Union, Literal, Optional  # noqa: F401

from fastapi import (  # noqa: F401
    APIRouter,
    Body,
    Cookie,
    Depends,
    Form,
    Header,
    HTTPException,
    Path,
    Query,
    Response,
    Security,
    status, UploadFile,
)
from fastapi.responses import PlainTextResponse

from submit_ce.api.config import config
from submit_ce.api.implementations.default_api_base import BaseDefaultApi
from submit_ce.api.domain import Submission
from submit_ce.api.domain.meta import CategoryChange
from submit_ce.api.domain.events import AgreedToPolicy, StartedNew, StartedAlterExising, SetLicense, AuthorshipDirect, \
    AuthorshipProxy, SetCategories, SetMetadata, VerifyUser
from submit_ce.api.auth import get_user, get_client
from submit_ce.api.implementations import ImplementationConfig

if not isinstance(config.submission_api_implementation, ImplementationConfig):
    raise ValueError("submission_api_implementation must be of class ImplementationConfig.")

implementation: BaseDefaultApi = config.submission_api_implementation.impl
"""Implementation to use for the API."""

impl_depends: Callable = config.submission_api_implementation.depends_fn
"""A depends the implementation depends on."""

userDep = Depends(get_user)
clentDep = Depends(get_client)

router = APIRouter()
router.prefix="/v1"


@router.post(
    "/start",
    response_class=PlainTextResponse,
    responses={
        200: {"description": "Successfully started a submission."},
    },
    tags=["submit"],
)
async def start(started: Union[StartedNew, StartedAlterExising],
                impl_dep=Depends(impl_depends), user=userDep, client=clentDep,
                ) -> str:
    """Start a submission and get a submission ID.

    TODO Maybe the start needs to include accepting an agreement?

    TODO How to better indicate that the body is a string that is the submission id? Links?"""
    return implementation.start(impl_dep, user, client, started)


@router.get(
    "/user_submissions",
    tags=["info"],
)
async def user_submissions(impl_dep=Depends(impl_depends),
                           user=userDep, client=clentDep) -> List[object]:
    """Get the existing submissions and papers for a user."""
    return implementation.user_submissions(impl_dep, user, client)


@router.get(
    "/submission/{submission_id}",
    responses={
        200: {"model": object, "description": "The submission data."},
    },
    tags=["submit"],
    response_model_by_alias=True,
)
async def get_submission(
        submission_id: str = Path(..., description="Id of the submission to get."),
        impl_dep=Depends(impl_depends), user=userDep, client=clentDep
) -> Submission:
    """Get information about a submission."""
    return implementation.get_submission(impl_dep, user, client, submission_id)


@router.post(
    "/submission/{submission_id}/acceptPolicy",
    responses={
        200: {"model": object, "description": "The has been accepted."},
        400: {"model": str, "description": "There was an problem when processing the agreement. It was not accepted."},
        401: {"description": "Unauthorized. Missing valid authentication information. The agreement was not accepted."},
        403: {"description": "Forbidden. User or client is not authorized to upload. The agreement was not accepted."},
        500: {"description": "Error. There was a problem. The agreement was not accepted."},
    },
    tags=["submit"],
)
async def accept_policy_post(
        submission_id: str = Path(..., description="Id of the submission to get."),
        agreement: AgreedToPolicy = Body(None, description=""),
        impl_dep: dict = Depends(impl_depends),
        user=userDep, client=clentDep
) -> object:
    """Agree to an arXiv policy to initiate a new item submission or  a change to an existing item. """
    return implementation.accept_policy_post(impl_dep, user, client, submission_id, agreement)


@router.post(
    "/submission/{submission_id}/verifyUser",
    tags=["submit"],
)
async def verify_user_post(
        submission_id: str = Path(...,
                                  description="Assert user account info is correct."),
        verifyUser: VerifyUser = Body(None,
                                      description="Indication that the user has reviwed their info and it is correct."),
        impl_dep: dict = Depends(impl_depends),
        user=userDep, client=clentDep
) -> str:
    return implementation.verify_user_post(impl_dep, user, client, submission_id, verifyUser)


@router.post(
    "/submission/{submission_id}/assertAuthorship",
    tags=["submit"],
)
async def assert_authorship_post(
        submission_id: str = Path(..., description="Id of the submission to assert authorship for."),
        authorship: Union[AuthorshipDirect, AuthorshipProxy] = Body(None, description=""),
        impl_dep: dict = Depends(impl_depends),
        user=userDep, client=clentDep
) -> str:
    return implementation.assert_authorship_post(impl_dep, user, client, submission_id, authorship)


@router.post(
    "/submission/{submission_id}/setLicense",
    tags=["submit"],
)
async def set_license_post(
        submission_id: str = Path(..., description="Id of the submission to set the license for."),
        license: SetLicense = Body(None, description="The license to set"),
        impl_dep: dict = Depends(impl_depends),
        user=userDep, client=clentDep
) -> None:
    """Set a license for a files of a submission."""
    return implementation.set_license_post(impl_dep, user, client, submission_id, license)

@router.post(
    "/submission/{submission_id}/files",
    tags=["submit"],
)
async def file_post(
        uploadFile: UploadFile,  # waring: this uses https://docs.python.org/3/library/tempfile.html#tempfile.SpooledTemporaryFile
        submission_id: str = Path(..., description="Id of the submission to add the upload to."),
        impl_dep: dict = Depends(impl_depends),
        user=userDep, client=clentDep
)->str:
    """Upload a file to a submission.

    The file can be a single file, a zip, or a tar.gz. Zip and tar.gz files will be unpacked.
    """
    return implementation.file_post(impl_dep, user, client, submission_id, uploadFile)


@router.post(
    "/submission/{submission_id}/setCategories",
    tags=["submit"],
)
async def set_categories_post(set_categoires: SetCategories,
                              submission_id: str = Path(..., description="Id of the submission to set the categories for."),
                              impl_dep: dict = Depends(impl_depends),
                              user=userDep, client=clentDep
                              ) -> CategoryChange:
    """Set the categories for a submission.

    The categories will replace any categories already set on the submission."""
    return implementation.set_categories_post(impl_dep, user, client, submission_id, set_categoires)

@router.post(
    "/submission/{submission_id}/setMetadata",
    tags=["submit"],
)
async def set_metadata_post(metadata: Union[SetMetadata],
                            submission_id: str = Path(..., description="Id of the submission to set the metadata for."),
                            impl_dep: dict = Depends(impl_depends),
                            user=userDep, client=clentDep) -> str:
    return implementation.set_metadata_post(impl_dep, user, client, submission_id, metadata)
"""
/files get post head delete

/files/{path} get post head delete

process post

preview post get head delete

metadata get post head delete

optional metadata get post head delete

finalize (aka submit) post 
"""
@router.post(
    "/submission/{submission_id}/markDeposited",
    responses={
        200: {"description": "Deposited has been recorded."},
    },
    tags=["post submit"],
    response_model_by_alias=True,
)
async def mark_deposited_post(
        submission_id: str = Path(..., description="Id of the submission to get."),
        impl_dep: dict = Depends(impl_depends), user=userDep, client=clentDep
) -> None:
    """Mark that the submission has been successfully deposited into the arxiv corpus."""
    return implementation.mark_deposited_post(impl_dep, user, client, submission_id)


@router.post(
    "/submission/{submission_id}/markProcessingForDeposit",
    responses={
        200: {"description": "The submission has been marked as in processing for deposit."},
    },
    tags=["post submit"],
    response_model_by_alias=True,
)
async def _mark_processing_for_deposit_post(
        submission_id: str = Path(..., description="Id of the submission to get."),
        impl_dep: dict = Depends(impl_depends), user=userDep, client=clentDep
) -> None:
    """Mark that the submission is being processed for deposit."""
    return implementation.mark_processing_for_deposit_post(impl_dep, user, client, submission_id)


@router.post(
    "/submission/{submission_id}/unmarkProcessingForDeposit",
    responses={
        200: {"description": "The submission has been marked as no longer in processing for deposit."},
    },
    tags=["post submit"],
    response_model_by_alias=True,
)
async def unmark_processing_for_deposit_post(
        submission_id: str = Path(..., description="Id of the submission to get."),
        impl_dep: dict = Depends(impl_depends), user=userDep, client=clentDep
) -> None:
    """Indicate that an external system in no longer working on depositing this submission.

    This just indicates that the submission is no longer in processing state. This does not indicate that it
     was successfully deposited. """
    return implementation.unmark_processing_for_deposit_post(impl_dep, user, client, submission_id)

@router.get(
    "/status",
    responses={
        200: {"description": "system is working correctly"},
        500: {"description": "system is not working correctly"},
    },
    tags=["service"],
    response_model_by_alias=True,
)
async def get_service_status(impl_dep: dict = Depends(impl_depends)) -> str:
    """Get information about the current status of file management service."""
    return implementation.get_service_status(impl_dep)
