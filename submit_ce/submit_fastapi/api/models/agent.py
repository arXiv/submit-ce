"""Data structures for agents."""

from typing import Any, Optional, List, Union, Type, Dict

from pydantic import BaseModel, Field


class User(BaseModel):
    """A human end user."""

    username: str
    forename: str
    surname: str
    suffix: str
    identifier: Optional[str] = Field(default=None)
    affiliation: str
    email: str
    endorsements: List[str] = Field(default_factory=list)

    def get_name(self) -> str:
        """Full name of the user."""
        return f"{self.forename} {self.surname} {self.suffix}"



class Client(BaseModel):
    """A non-human tool that is making requests to the submit API, usually an API client."""
    remoteAddress: str
    remoteHost: str
    agent_type:  str
    agent_version: str
