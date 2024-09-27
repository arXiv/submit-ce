import uuid
from arxiv.auth.auth.tokens import decode
from typing import Optional, Callable, Annotated

from arxiv.auth.domain import Session
from fastapi import Request, Depends
from fastapi.security import OAuth2PasswordBearer

from submit_ce.api.domain.agent import User, Client

oauth2_schema = OAuth2PasswordBearer(
    tokenUrl="token" # url to OAuth2 (relative)
)


async def user_getter_impl(request: Request)->Callable[[Request, str], User]:
    return request.app.state.config.submission_api_implementation.userid_to_user

async def get_user(token: Annotated[str, Depends(oauth2_schema)], request: Request) -> User:
    """Decode a NG JWT token."""
    to_user_fn = await user_getter_impl(request)
    user = to_user_fn(request, token)
    return user


async def get_client(request: Request) -> Client:
    """Gets the client tool the user is connecting with. Ex. Browser, submission ui frontend"""
    # TODO some kind of implementation

    ua = request.headers.get("User-Agent", None)
    if ua is None:
        agent_type="ua-not-set"
    if ua.lower().startswith("mozilla"):
        agent_type="browser"
    else:
        agent_type=ua[:20]

    # todo hostname

    return Client(
        remoteAddress=request.client.host,
        remoteHost="",
        agent_type=agent_type,
        # agent_version="v223432"
    )

