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

from submit_ce.api.domain import Submission, Event
from submit_ce.fastapi.auth import get_user, get_client

# if not isinstance(config.submission_api_implementation, ImplementationConfig):
#     raise ValueError("submission_api_implementation must be of class ImplementationConfig.")


#impl_depends: Callable = config.submission_api_implementation.depends_fn
impl_depends: Callable = lambda x: {}
"""A depends the implementation depends on."""

userDep = Depends(get_user)
clentDep = Depends(get_client)

router = APIRouter()
router.prefix="/v1"


@router.get(
    "/submission/{submission_id}",
    response_model=Submission,
    )
async def load(submission_id: str) -> Submission:
    #return implementation.load(submission_id)
    raise HTTPException(status_code=404)

@router.get(
    "/submissions_for_user/{user_id}",
    response_model=List[Submission],
)
async def load_submissions_for_user(user_id: str) -> List[Submission]:
    raise HTTPException(status_code=404)
    #return implementation.load_submissions_for_user(user_id)

@router.get(
    "/submissions_for_user/{user_id}",
    response_model=List[Submission],
)
async def load_submissions_for_user(user_id: str) -> List[Submission]:
    raise HTTPException(status_code=404)
    #return implementation.load_submissions_for_user(user_id)


AllEventTypes= Union[tuple(Event.__subclasses__())]
@router.post(
    "/submission/{submission_id}",
    response_model=Submission,
)
async def save(submission_id: str, events: AllEventTypes) -> Submission:
    raise HTTPException(status_code=404)