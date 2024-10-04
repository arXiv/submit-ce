"""Data structures for agents."""

from typing import Any, Optional, List, Union, Type, Dict

from pydantic import BaseModel, Field


class User(BaseModel):
    """A human end user."""
    identifier: Optional[str] = Field(default=None)
    """System identifier for the user. Ex a username, user_id or tapir nickname."""

    forename: str
    surname: str
    suffix: str

    email: str

    affiliation: str
    endorsements: List[str] = Field(default_factory=list)

    def get_name(self) -> str:
        """Full name of the user."""
        return f"{self.forename} {self.surname} {self.suffix}"



class Client(BaseModel):
    """A non-human tool that is making requests to the submit API, usually an API client."""
    remoteAddress: str
    remoteHost: Optional[str] = Field(default=None)
    agent_type:  str
    agent_version: Optional[str] = Field(default=None)
