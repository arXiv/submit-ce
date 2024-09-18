# coding: utf-8

from typing import Dict, List, Callable, Annotated, Union, Literal  # noqa: F401

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
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from submit_ce.submit_fastapi.config import config

from .default_api_base import BaseDefaultApi
from .models.events import AgreedToPolicy, StartedNew, StartedAlterExising
from ..auth import get_user, get_client
from ..implementations import ImplementationConfig

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
    return await implementation.start(impl_dep, user, client, started)


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
) -> object:
    """Get information about a submission."""
    return await implementation.get_submission(impl_dep, user, client, submission_id)


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
    response_model_by_alias=True,
)
async def accept_policy_post(
        submission_id: str = Path(..., description="Id of the submission to get."),
        agreement: AgreedToPolicy = Body(None, description=""),
        impl_dep: dict = Depends(impl_depends),
        user=userDep, client=clentDep
) -> object:
    """Agree to an arXiv policy to initiate a new item submission or  a change to an existing item. """
    return await implementation.accept_policy_post(impl_dep, user, client, submission_id, agreement)


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
    return await implementation.mark_deposited_post(impl_dep, user, client, submission_id)


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
    return await implementation.mark_processing_for_deposit_post(impl_dep, user, client, submission_id)


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
    return await implementation.unmark_processing_for_deposit_post(impl_dep, user, client, submission_id)

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
    return await implementation.get_service_status(impl_dep)
