"""Routes for the submission mutation API.

Every mutation builds a domain `Event` and calls `SubmitApi.save()`, so it
inherits the event log and the row-lock critical section. Endpoints are sync
(``def``) so FastAPI runs them on a threadpool thread, giving each request its
own SQLAlchemy session (see `submit_ce.implementations.legacy_implementation.
fastapi_impl`).

Phase 1 (SUBMISSION-257): resubmit + reads. remove/unremove land next, with
their new domain events (`AdminRemove`, `UnRemove`).
"""
import logging
from typing import Optional

from pydantic import BaseModel

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.encoders import jsonable_encoder

from submit_ce.domain.event import CreateSubmissionVersion, AdminRemove, UnRemove
from submit_ce.domain.exceptions import NoSuchSubmission, InvalidEvent
from submit_ce.fastapi.auth import get_user_and_client

logger = logging.getLogger(__name__)

router = APIRouter()


class MutationComment(BaseModel):
    """Optional free-text reason, recorded in the classic admin log."""

    comment: Optional[str] = None


def _api(request: Request):
    """The `SubmitApi` wired onto the app at startup."""
    return request.app.state.api


@router.get("/submission/{submission_id}", tags=["read"])
def get_submission(submission_id: str, request: Request):
    """Return the current state of a submission."""
    try:
        submission = _api(request).get(submission_id)
    except NoSuchSubmission as exc:
        raise HTTPException(status_code=404, detail="No such submission") from exc
    return jsonable_encoder(submission)


@router.get("/submission/{submission_id}/with_history", tags=["read"])
def get_submission_with_history(submission_id: str, request: Request):
    """Return a submission plus its applied event history."""
    try:
        submission, events = _api(request).get_with_history(submission_id)
    except NoSuchSubmission as exc:
        raise HTTPException(status_code=404, detail="No such submission") from exc
    return jsonable_encoder({"submission": submission, "events": events})


@router.post("/submission/{submission_id}/resubmit", status_code=201,
             tags=["mutate"])
def resubmit(submission_id: str, request: Request,
             user_client=Depends(get_user_and_client)):
    """Create a new working version of an announced submission (replace/resubmit).

    Maps to the existing `CreateSubmissionVersion` event: announced -> new
    ``working`` version (type ``rep``).
    """
    user, client = user_client
    event = CreateSubmissionVersion(creator=user, client=client)
    try:
        submission, _ = _api(request).save(event, submission_id=submission_id)
    except NoSuchSubmission as exc:
        raise HTTPException(status_code=404, detail="No such submission") from exc
    except InvalidEvent as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return jsonable_encoder(submission)


@router.post("/submission/{submission_id}/remove", status_code=200,
             tags=["mutate"])
def remove(submission_id: str, request: Request,
           body: Optional[MutationComment] = None,
           user_client=Depends(get_user_and_client)):
    """Administratively remove a submission from the queue (-> ``removed``/9).

    The admin/moderator remove used by arxiv-check. Reversible with unremove.
    An optional ``comment`` is recorded in the classic admin log.
    """
    user, client = user_client
    event = AdminRemove(creator=user, client=client,
                        comment=body.comment if body else None)
    try:
        submission, _ = _api(request).save(event, submission_id=submission_id)
    except NoSuchSubmission as exc:
        raise HTTPException(status_code=404, detail="No such submission") from exc
    except InvalidEvent as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return jsonable_encoder(submission)


@router.post("/submission/{submission_id}/unremove", status_code=200,
             tags=["mutate"])
def unremove(submission_id: str, request: Request,
             body: Optional[MutationComment] = None,
             user_client=Depends(get_user_and_client)):
    """Reverse a remove: a removed submission goes back to on hold (-> 2).

    An optional ``comment`` is recorded in the classic admin log.
    """
    user, client = user_client
    event = UnRemove(creator=user, client=client,
                     comment=body.comment if body else None)
    try:
        submission, _ = _api(request).save(event, submission_id=submission_id)
    except NoSuchSubmission as exc:
        raise HTTPException(status_code=404, detail="No such submission") from exc
    except InvalidEvent as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return jsonable_encoder(submission)
