"""Authentication for the submission mutation API.

Callers present an arXiv NG JWT as ``Authorization: Bearer <token>``. This is
the service/admin audience (arxiv-check and other backends), so unlike SWORD --
which uses HTTP Basic for depositors -- this API uses bearer tokens, mirroring
how the Flask UI decodes them (`submit_ce.ui.auth`).

TODO(SUBMISSION-257): endorsements are not enriched from the DB here (the JWT
does not carry them). The Phase-1 events (resubmit/remove/unremove) do not need
them; add DB enrichment before exposing events that do (e.g. classification).
"""
import logging
from typing import Tuple

from fastapi import Request, HTTPException, status

from arxiv.auth.auth.tokens import decode
from arxiv.auth.auth.exceptions import InvalidToken, ExpiredToken, MissingToken

from submit_ce.domain import User, Client, HttpClient
from submit_ce.domain.agent import user_from_session
from submit_ce.ui.config import settings

logger = logging.getLogger(__name__)

_UNAUTH = {"WWW-Authenticate": "Bearer"}


def _bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Missing bearer token", headers=_UNAUTH)
    return header.split(" ", 1)[1].strip()


def _client(request: Request) -> Client:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        remote_addr = forwarded.split(",")[-1].strip()
    else:
        remote_addr = request.client.host if request.client else "unknown"
    return HttpClient(remote_addr=remote_addr)


def get_user_and_client(request: Request) -> Tuple[User, Client]:
    """FastAPI dependency: decode the bearer token to a domain ``User`` + ``Client``."""
    token = _bearer_token(request)
    try:
        session = decode(token, settings.JWT_SECRET)
    except (InvalidToken, ExpiredToken, MissingToken) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail=f"Invalid token: {exc}", headers=_UNAUTH) from exc
    try:
        user = user_from_session(session)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Token has no user", headers=_UNAUTH) from exc
    return user, _client(request)
