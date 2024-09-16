# coding: utf-8

from typing import Dict, List  # noqa: F401
import importlib
import pkgutil

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

from .models.extra_models import TokenModel  # noqa: F401
from .models.agreement import Agreement


router = APIRouter()

BaseDefaultApi = None

@router.get(
    "/status",
    responses={
        200: {"description": "system is working correctly"},
        500: {"description": "system is not working correctly"},
    },
    tags=["default"],
    response_model_by_alias=True,
)
async def get_service_status(
) -> None:
    """Get information about the current status of file management service."""
    if not BaseDefaultApi.subclasses:
        raise HTTPException(status_code=500, detail="Not implemented")
    return await BaseDefaultApi.subclasses[0]().get_service_status()


@router.get(
    "/{submission_id}",
    responses={
        200: {"model": object, "description": "The submission data."},
    },
    tags=["default"],
    response_model_by_alias=True,
)
async def get_submission(
    submission_id: str = Path(..., description="Id of the submission to get."),
) -> object:
    """Get information about a submission."""
    if not BaseDefaultApi.subclasses:
        raise HTTPException(status_code=500, detail="Not implemented")
    return await BaseDefaultApi.subclasses[0]().get_submission(submission_id)


@router.post(
    "/",
    responses={
        200: {"model": str, "description": "Successfully started a new submission."},
    },
    tags=["default"],
    response_model_by_alias=True,
)
async def new(
) -> str:
    """Start a submission and get a submission ID."""
    if not BaseDefaultApi.subclasses:
        raise HTTPException(status_code=500, detail="Not implemented")
    return await BaseDefaultApi.subclasses[0]().new()


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
) -> object:
    """Agree to a an arXiv policy to initiate a new item submission or  a change to an existing item. """
    if not BaseDefaultApi.subclasses:
        raise HTTPException(status_code=500, detail="Not implemented")
    return await BaseDefaultApi.subclasses[0]().submission_id_accept_policy_post(submission_id, agreement)


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
) -> None:
    """The submission has been successfully deposited by an external service."""
    if not BaseDefaultApi.subclasses:
        raise HTTPException(status_code=500, detail="Not implemented")
    return await BaseDefaultApi.subclasses[0]().submission_id_deposited_post(submission_id)


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
) -> None:
    """Mark that the submission is being processed for deposit."""
    if not BaseDefaultApi.subclasses:
        raise HTTPException(status_code=500, detail="Not implemented")
    return await BaseDefaultApi.subclasses[0]().submission_id_mark_processing_for_deposit_post(submission_id)


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
) -> None:
    """Indicate that an external system in no longer working on depositing this submission.  This does not indicate that is was successfully deposited. """
    if not BaseDefaultApi.subclasses:
        raise HTTPException(status_code=500, detail="Not implemented")
    return await BaseDefaultApi.subclasses[0]().submission_id_unmark_processing_for_deposit_post(submission_id)
