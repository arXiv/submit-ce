# coding: utf-8

from typing import Dict, List, Callable  # noqa: F401

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

from submit_ce.submit_fastapi.config import config

from .default_api_base import BaseDefaultApi
from .models.agreement import Agreement
from ..implementations import ImplementationConfig

if not isinstance(config.submission_api_implementation, ImplementationConfig):
    raise ValueError("submission_api_implementation must be of class ImplementationConfig.")

implementation: BaseDefaultApi = config.submission_api_implementation.impl
"""Implementation to use for the API."""

impl_depends: Callable = config.submission_api_implementation.depends_fn
"""A depends the implementation depends on."""

router = APIRouter()

@router.get(
    "/status",
    responses={
        200: {"description": "system is working correctly"},
        500: {"description": "system is not working correctly"},
    },
    tags=["service"],
    response_model_by_alias=True,
)
async def get_service_status(impl_dep: dict = Depends(impl_depends)) -> None:
    """Get information about the current status of file management service."""
    print("Here in default_api get_service_status")
    return await implementation.get_service_status(impl_dep)


@router.post(
    "/",
    responses={
        200: {"model": str, "description": "Successfully started a submission."},
    },
    tags=["submit"],
    response_model_by_alias=True,
)
async def start(impl_dep = Depends(impl_depends)) -> str:
    """Start a submission and get a submission ID.

    TODO Maybe the start needs to include accepting an agreement?

    TODO parameters for new,replacement,withdraw,cross,jref

    TODO How to better indicate that the body is a string that is the submission id? Links?"""
    return await implementation.start(impl_dep)


@router.get(
    "/{submission_id}",
    responses={
        200: {"model": object, "description": "The submission data."},
    },
    tags=["submit"],
    response_model_by_alias=True,
)
async def get_submission(
    submission_id: str = Path(..., description="Id of the submission to get."),
        impl_dep = Depends(impl_depends)
) -> object:
    """Get information about a submission."""
    return await implementation.get_submission(impl_dep, submission_id)


@router.post(
    "/{submission_id}/acceptPolicy",
    responses={
        200: {"model": object, "description": "The has been accepted."},
        400: {"model": str, "description": "There was an problem when processing the agreement. It was not accepted."},
        401: {"description": "Unauthorized. Missing valid authentication information. The agreement was not accepted."},
        403: {"description": "Forbidden. Client or user is not authorized to upload. The agreement was not accepted."},
        500: {"description": "Error. There was a problem. The agreement was not accepted."},
    },
    tags=["submit"],
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
    "/{submission_id}/deposited",
    responses={
        200: {"description": "Deposited has been recorded."},
    },
    tags=["postsubmit"],
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
    tags=["postsubmit"],
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
    tags=["postsubmit"],
    response_model_by_alias=True,
)
async def submission_id_unmark_processing_for_deposit_post(
    submission_id: str = Path(..., description="Id of the submission to get."),
    impl_dep: dict = Depends(impl_depends),
) -> None:
    """Indicate that an external system in no longer working on depositing this submission.  This does not indicate that is was successfully deposited. """
    return await implementation.submission_id_unmark_processing_for_deposit_post(impl_dep, submission_id)


