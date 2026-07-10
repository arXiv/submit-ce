"""Classes for users to save with `Events`.

TODO This whole file is not good. This is all code from NG.

What is the goal of this? Not clear. It seems like this was intended to support non-human "agent" type of auth.
When it was written arxiv-ng already had a auth setup that was intend to be used, so why does this have such
a different structure? This was written by the same person who wrote the arxiv-ng auth code. Why did they use
ambiguous terminology? Why did they use such a different structure than what was in arxiv-ng auth?

Problem: arxiv-base Client and submit-ng Client are very different
Problem: There is no simple mapping from arxiv-base auth Session and these classes
Problem: native_id is a mess
Problem: Class names are a ambiguous and overlap with arxiv-base class names
"""

from __future__ import annotations
from typing import Union, Literal, Annotated, Optional

__all__ = ("User", "Client", "ServiceAgent", "HttpClient", "InternalClient", "user_from_session",
           "PublicUser", "StaffUser", "System", "agent_factory")

from arxiv.auth import auth
from pydantic import BaseModel, Field, TypeAdapter


class PublicUser(BaseModel):
    """A non staff submitting user.

    Intentionally lacks name field, get that from user store."""
    user_id: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=3, max_length=100)  # max of (length in arXiv_submissions, length tapir_user.first_name + last_name)
    email: str = Field(min_length=3, max_length=255)  # max of (length arXiv_submissions, length in tapir_user)
    endorsements: list[str] = []
    scopes: list[str] = []
    agent_type: Literal["PublicUser"] = "PublicUser"

    @property
    def identifier(self):
        return self.user_id

    @property
    def is_proxy(self):
        return auth.scopes.PROXY_SUBMISSION in self.scopes


class StaffUser(BaseModel):
    """A staff user.

    Name can be recorded here."""
    user_id: str = Field(min_length=3, max_length= 30)
    email: str = Field(min_length=3, max_length= 255)
    name: str = Field(min_length=3, max_length= 100)
    username: str = Field(min_length=3, max_length= 100)
    endorsements: list[str] = []
    scopes: list[str] = []
    agent_type: Literal["StaffUser"] = "StaffUser"

    @property
    def identifier(self):
        return self.user_id

    @property
    def is_proxy(self):
        return auth.scopes.PROXY_SUBMISSION in self.scopes



class ServiceAgent(BaseModel):
    """Represents a service agent."""
    email: str = Field(min_length=3, max_length= 255)
    agent_type: Literal["ServiceAgent"] = "ServiceAgent"

    @property
    def identifier(self):
        return self.email


class System(BaseModel):
    """Internal system not used with service agent credentials."""
    name: str = Field(min_length=3, max_length= 100)
    agent_type: Literal["System"] = "System"

    @property
    def identifier(self):
        return self.name

User = Annotated[
    Union[PublicUser, StaffUser, System, ServiceAgent],
    Field(discriminator="agent_type")
]


class HttpClient(BaseModel):
    """Represents the tool used to send the HTTP request to the app or API."""
    remote_addr: str
    remote_host: Optional[str] = None
    version: Optional[str] = None
    device_type: Optional[str] = None
    language: Optional[str] = None
    trace_headers: Optional[str] = None
    tool:  Literal["HttpClient"] = "HttpClient"


class InternalClient(BaseModel):
    """Only use this to represent actions taken by the code in submit_ce.

    This should not be used for internally operated tools that connect to the submit API via HTTP. Use
    `HttpClient` for those."""
    name: str
    trace_headers: Optional[str] = None
    tool: Literal["InternalClient"] = "InternalClient"

    @property
    def remote_addr(self) -> str:
        return ""

    @property
    def remote_host(self) -> str:
        return ""


Client = Annotated[
    Union[HttpClient, InternalClient],
    Field(discriminator="tool")]


_USER_ADAPTER = TypeAdapter(User)


def agent_factory(**data: dict) -> User:
    """Instantiate a subclass of :class:`.Agent`."""
    return _USER_ADAPTER.validate_python(data)


def user_from_session(session: auth.domain.Session, include_name=False) -> User:
    """There is a mismatch between what we get about the user from the
    arxiv.auth.domain.Session and what is in the submit-ce User.

    Note: name is options since it is joined from the user table.
    """
    if not session or not session.user or not session.user.user_id:
        raise RuntimeError("must pass session with user")
    if include_name:
        return StaffUser(
            user_id=session.user.user_id,
            email=session.user.email,
            username=session.user.username,
        )
    else:
        return PublicUser(
            user_id=session.user.user_id,
            email=session.user.email,
        )
