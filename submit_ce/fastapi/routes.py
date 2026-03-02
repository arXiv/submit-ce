"""
The API Paths for submit.

NOTE: changes to path tags change the package names in the generated API
"""
from datetime import datetime
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
from submit_ce.fastapi.auth import get_user, get_client

from submit_ce.api.domain import Submission, Event, Upload
from submit_ce.api.domain.process import ProcessStatus

# if not isinstance(config.submission_api_implementation, ImplementationConfig):
#     raise ValueError("submission_api_implementation must be of class ImplementationConfig.")


#impl_depends: Callable = config.submission_api_implementation.depends_fn
impl_depends: Callable = lambda x: {}
"""A depends the implementation depends on."""

userDep = Depends(get_user)
clentDep = Depends(get_client)

router = APIRouter()


@router.get(
    "/submission/{submission_id}",
    response_model=Submission,
    )
async def get(submission_id: str) -> Submission:
    #return implementation.load(submission_id)
    raise HTTPException(status_code=404)


@router.get("/submission/{submission_id}/with_history", response_model=Submission)
async def get_with_history(submission_id: str) -> Submission:
    raise HTTPException()



AllEventTypes= Union[tuple(Event.__subclasses__())]
@router.patch(
    "/submission/{submission_id}",
    response_model=Submission,
)
async def save_changes(submission_id: str, events: AllEventTypes) -> Submission:
    raise HTTPException(status_code=404)


@router.get("/submission/{submission_id}/workspace",
            response_model=Upload|None,
            tags=["workspace"],
            )
async def workspace_get(submission_id: str):
    raise HTTPException()

@router.delete("/submission/{submission_id}/workspace",
               tags=["workspace"]
               )
async def workspace_del(submission_id: str):
    raise HTTPException()


@router.get("/submission/{submission_id}/workspace/source",
            tags=["workspace"]
            )
async def source_pacakage_post(submission_id: str):
    raise HTTPException()


@router.post("/submission/{submission_id}/workspace/source",
             tags=["workspace"])
async def source_pacakage_post(submission_id: str, file: UploadFile):
    raise HTTPException()


@router.post("/submission/{submission_id}/workspace/source/checksum",
             response_model=str,
             tags=["workspace"])
async def source_pacakage_checksum(submission_id: str):
    raise HTTPException()



@router.get("/submission/{submission_id}/workspace/view",
            tags=["workspace"]
            )
async def view_get(submission_id: str):
    raise HTTPException()


@router.head("/submission/{submission_id}/workspace/view",
             tags=["workspace"]
             )
async def view_head(submission_id: str):
    # this probably covers both get_preview_checksum and get_preview_exist    
    raise HTTPException()

@router.post("/submission/{submission_id}/process",
             tags=["process"]
             )
async def process_start(submission_id: str):
    raise HTTPException()

@router.head("/submission/{submission_id}/process/{process_id}",
             tags=["process"],
             response_model=ProcessStatus)
async def process_head(submission_id: str, process_id: str):
    raise HTTPException()
    


@router.get(
    "/user/{user_id}/submissions",
    response_model=List[Submission],
    tags=["User"]
)
async def user_submissions(user_id: str) -> List[Submission]:
    raise HTTPException(status_code=404)
    #return implementation.load_submissions_for_user(user_id)

@router.get(
    "/user/{user_id}/categories",
    response_model=List[Submission],
    tags=["User"]
)
async def user_categories(user_id: str) -> List:
    raise HTTPException(status_code=404)
    #return implementation.load_submissions_for_user(user_id)


@router.get("/info/next_announcement_time",
            response_model=datetime,
            tags=["Informational"]
            )
async def info_next_announcement_time():
    raise HTTPException()


@router.get("/info/next_freeze_time",
            response_model=datetime,
            tags=["Informational"]
            )
async def info_next_freeze_time():
    raise HTTPException()
