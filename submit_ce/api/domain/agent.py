"""Data structures for agents."""

import hashlib
import ipaddress
from typing import Any, Optional, List, Union, Type, Dict

from dataclasses import field


__all__ = ('Agent', 'User', 'System', 'Client', 'agent_factory')

from pydantic.dataclasses import dataclass

# BDC: This uses dataclass instead of pydantic BaseModel only because it is more work to setup
# init vars from both the parent class and subclass in the instance.
# I'm tyring to get this working quickly, I didn't bother.
# Pydantic objects that are dataclasses need to be converted to and from JSON differently
# https://docs.pydantic.dev/latest/concepts/dataclasses/#json-dumping
@dataclass
class Agent:
    """
    Base class for agents in the submission system.

    An agent is an actor/system that generates/is responsible for events.
    """

    native_id: str
    """Type-specific identifier for the agent. This might be an URI."""

    hostname: Optional[str] = None
    """Hostname or IP address from which user requests are originating."""

    name: str = field(default_factory=str)
    username: str = field(default_factory=str)
    email: str = field(default_factory=str)
    endorsements: List[str] = field(default_factory=list)

    class Config:
        orm_model = True

    @property
    def agent_type(self):
        return self.__class__.__name__

    @property
    def agent_identifier(self):
        """
        Get the unique identifier for this agent instance.

        Based on both the agent type and native ID.
        """
        h = hashlib.new('sha1')
        h.update(b'%s:%s' % (self.agent_type.encode('utf-8'),
                             str(self.native_id).encode('utf-8')))
        return h.hexdigest()

    @classmethod
    def get_agent_type(cls):
        return cls.__name__

    # def model_post_init(self, *args) -> None:
    #     """Set derivative fields."""
    #     self.agent_type = self.__class__.get_agent_type()
    #     self.agent_identifier = self.get_agent_identifier()
    #
    # @classmethod
    # def get_agent_type(cls) -> str:
    #     """Get the name of the instance's class."""
    #     return cls.__name__
    #
    # def get_agent_identifier(self) -> str:

    def __eq__(self, other: Any) -> bool:
        """Equality comparison for agents based on type and identifier."""
        if not isinstance(other, self.__class__):
            return False
        return self.agent_identifier == other.agent_identifier


class User(Agent):
    """A human end user."""

    forename: str = field(default_factory=str)
    surname: str = field(default_factory=str)
    suffix: str = field(default_factory=str)
    identifier: Optional[str] = field(default=None)
    affiliation: str = field(default_factory=str)

    def model_post_init(self, *args) -> None:
        """Set derivative fields."""
        self.name = self.get_name()

    def get_name(self) -> str:
        """Full name of the user."""
        return f"{self.forename} {self.surname} {self.suffix}"


# TODO: extend this to support arXiv-internal services.
class System(Agent):
    """The submission application (this application)."""

    def model_post_init(self, *args) -> None:
        """Set derivative fields."""
        self.username = self.native_id
        self.name = self.native_id
        self.hostname = self.native_id


class Client(Agent):
    """A non-human third party, usually an API client."""

    remote_addr: ipaddress.ip_address

    # hostname: Optional[str] = field(default=None)
    # """Hostname or IP address from which client requests are originating."""

    def model_post_init(self) -> None:
        """Set derivative fields."""
        self.username = self.native_id
        self.name = self.native_id


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
    data = {k: v for k, v in data.items() if k in klass.__dataclass_fields__}  # type: ignore
    return klass(native_id, **data)  # type: ignore
