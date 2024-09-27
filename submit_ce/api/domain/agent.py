"""Data structures for agents."""

from typing import Optional, List, Literal

from pydantic import BaseModel, Field


class Agent(BaseModel):
    identifier: Optional[str] = Field(default=None)
    """System identifier for the user. Ex a username, user_id or tapir nickname."""

    agent_type: str


class Automation(Agent):
    """A non-human user, Ex QA check process."""
    identifier: Optional[str] = Field(default=None)
    """System identifier for the user. Ex a username, user_id or tapir nickname."""

    agent_type: Literal['Automation'] = "Automation"


class User(Agent):
    """A human end user."""
    identifier: Optional[str] = Field(default=None)
    """System identifier for the user. Ex a username, user_id or tapir nickname."""

    forename: str
    surname: str
    suffix: str

    email: str

    affiliation: Optional[str] = None
    endorsements: List[str] = Field(default_factory=list)

    agent_type: Literal['User'] = "User"

    def get_name(self) -> str:
        """Full name of the user."""
        return f"{self.forename} {self.surname} {self.suffix}"



class Client(BaseModel):
    """A non-human tool that is making requests to the submit API, usually an API client.

    A client is not an Agent, it represents the tool used by the Agent."""
    remoteAddress: str
    remoteHost: Optional[str] = Field(default=None)
    agent_version: Optional[str] = Field(default=None)
