# coding: utf-8

from typing import Dict, List  # noqa: F401

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
    status,
)

from arxiv.submit_fastapi.config import config
from arxiv.submit_fastapi.api.models.extra_models import TokenModel  # noqa: F401
from arxiv.submit_fastapi.api.models.agreement import Agreement

implementation = config.submission_api_implementation()
impl_depends = config.submission_api_implementation_depends_function

router = APIRouter()

@router.get(
    "/status",
    responses={
        200: {"description": "system is working correctly"},
        500: {"description": "system is not working correctly"},
    },
    tags=["default"],
    response_model_by_alias=True,
)
async def get_service_status(impl_dep: dict = Depends(impl_depends)) -> None:
    """Get information about the current status of file management service."""
    return await implementation.get_service_status(impl_dep)


# @router.get(
#     "/{submission_id}",
#     responses={
#         200: {"model": object, "description": "The submission data."},
#     },
#     tags=["default"],
#     response_model_by_alias=True,
# )
# async def get_submission(
#     submission_id: str = Path(..., description="Id of the submission to get."),
# ) -> object:
#     """Get information about a submission."""
#     return await implementation.get_submission(submission_id)


# @router.post(
#     "/",
#     responses={
#         200: {"model": str, "description": "Successfully started a new submission."},
#     },
#     tags=["default"],
#     response_model_by_alias=True,
# )
# async def new(
# ) -> str:
#     """Start a submission and get a submission ID."""
#     return await implementation.new()


@router.post(
    "/{submission_id}/acceptPolicy",
    responses={
        200: {"model": object, "description": "The has been accepted."},
        400: {"model": str, "description": "There was an problem when processing the agreement. It was not accepted."},
        401: {"description": "Unauthorized. Missing valid authentication information. The agreement was not accepted."},
        403: {"description": "Forbidden. Client or user is not authorized to upload. The agreement was not accepted."},
        500: {"description": "Error. There was a problem. The agreement was not accepted."},
    },
    tags=["default"],
    response_model_by_alias=True,
)
async def submission_id_accept_policy_post(
    submission_id: str = Path(..., description="Id of the submission to get."),
    agreement: Agreement = Body(None, description=""),
    impl_dep: dict = Depends(impl_depends),
) -> object:
    """Agree to an arXiv policy to initiate a new item submission or  a change to an existing item. """
    return await implementation.submission_id_accept_policy_post(impl_dep, submission_id, agreement)


@router.post(
    "/{submission_id}/Deposited",
    responses={
        200: {"description": "Deposited has been recorded."},
    },
    tags=["default"],
    response_model_by_alias=True,
)
async def submission_id_deposited_post(
    submission_id: str = Path(..., description="Id of the submission to get."),
    impl_dep: dict = Depends(impl_depends),
) -> None:
    """The submission has been successfully deposited by an external service."""
    return await implementation.submission_id_deposited_post(impl_dep, submission_id)


@router.post(
    "/{submission_id}/markProcessingForDeposit",
    responses={
        200: {"description": "The submission has been marked as in procesing for deposit."},
    },
    tags=["default"],
    response_model_by_alias=True,
)
async def submission_id_mark_processing_for_deposit_post(
    submission_id: str = Path(..., description="Id of the submission to get."),
    impl_dep: dict = Depends(impl_depends),
) -> None:
    """Mark that the submission is being processed for deposit."""
    return await implementation.submission_id_mark_processing_for_deposit_post(impl_dep, submission_id)


@router.post(
    "/{submission_id}/unmarkProcessingForDeposit",
    responses={
        200: {"description": "The submission has been marked as no longer in procesing for deposit."},
    },
    tags=["default"],
    response_model_by_alias=True,
)
async def submission_id_unmark_processing_for_deposit_post(
    submission_id: str = Path(..., description="Id of the submission to get."),
    impl_dep: dict = Depends(impl_depends),
) -> None:
    """Indicate that an external system in no longer working on depositing this submission.  This does not indicate that is was successfully deposited. """
    return await implementation.submission_id_unmark_processing_for_deposit_post(impl_dep, submission_id)
