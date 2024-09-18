"""Data structures for agents."""

from typing import Any, Optional, List, Union, Type, Dict

from dataclasses import dataclass, field

from pydantic import BaseModel, Field


class Agent(BaseModel):
    """
    Base class for actors that are responsible for events.
    """

    native_id: str
    """
    Type-specific identifier for the agent. 
    
    In legacy this will be the tapir user_id
    This might be an URI.
    """

    hostname: Optional[str] = Field(default=None)
    """Hostname or IP address from which user requests are originating."""

    name: str
    username: str
    email: str
    endorsements: List[str] = Field(default_factory=list)

    @classmethod
    def get_agent_type(cls) -> str:
        """Get the name of the instance's class."""
        return cls.__name__

    def __eq__(self, other: Any) -> bool:
        """Equality comparison for agents based on type and identifier."""
        # if not isinstance(other, self.__class__):
        #     return False
        return self.native_id == other.native_id


class User(Agent):
    """A human end user."""

    forename: str = field(default_factory=str)
    surname: str = field(default_factory=str)
    suffix: str = field(default_factory=str)
    identifier: Optional[str] = field(default=None)
    affiliation: str = field(default_factory=str)

    def get_name(self) -> str:
        """Full name of the user."""
        return f"{self.forename} {self.surname} {self.suffix}"


class System(Agent):
    """The submission application."""
    pass


@dataclass
class Client(Agent):
    """A non-human third party, usually an API client."""
    pass


_agent_types: Dict[str, Type[Agent]] = {
    User.get_agent_type(): User,
    System.get_agent_type(): System,
    Client.get_agent_type(): Client,
}


def agent_factory(**data: Union[Agent, dict]) -> Agent:
    """Instantiate a subclass of :class:`.Agent`."""
    if isinstance(data, Agent):
        return data
    agent_type = str(data.pop('agent_type'))
    native_id = data.pop('native_id')
    if not agent_type or not native_id:
        raise ValueError('No such agent: %s, %s' % (agent_type, native_id))
    if agent_type not in _agent_types:
        raise ValueError(f'No such agent type: {agent_type}')

    # Mypy chokes on meta-stuff like this. One of the goals of this factory
    # function is to not have to write code for each agent subclass. We can
    # revisit this in the future. For now, this code is correct, it just isn't
    # easy to type-check.
    klass = _agent_types[agent_type]
    data = {k: v for k, v in data.items() if k in klass.__dataclass_fields__}
    return klass(native_id, **data)
