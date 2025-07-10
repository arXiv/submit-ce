"""
Proposals provide a mechanism for suggesting changes to submissions.

The primary use-case in the classic submission & moderation system is for
suggesting changes to the primary or cross-list classification. Such proposals
are generated both automatically based on the results of the classifier and
manually by moderators.
"""

from typing import Optional, List
from datetime import datetime

from dataclasses import dataclass, field
from enum import Enum

from .annotation import Comment
from .agent import User, agent_factory
from .util import get_tzaware_utc_now

__all__ = ['Proposal', 'Status']


class Status(Enum):
    PENDING = 'pending'
    REJECTED = 'rejected'
    ACCEPTED = 'accepted'


@dataclass
class Proposal:
    """Represents a proposal to apply an event to a submission."""


    event_id: str
    creator: User
    created: datetime = field(default_factory=get_tzaware_utc_now)
    # scope: str      # TODO: document this.
    proxy: Optional[User] = field(default=None)

    proposed_event_type: Optional[type] = field(default=None)
    proposed_event_data: dict = field(default_factory=dict)
    comments: List[Comment] = field(default_factory=list)
    status: Status = field(default=Status.PENDING)

    @property
    def proposal_type(self) -> str:
        """Name (str) of the type of annotation."""
        assert self.proposed_event_type is not None
        return self.proposed_event_type.__name__

    def __post_init__(self) -> None:
        """Check our enums and agents."""
        if self.creator and isinstance(self.creator, dict):
            self.creator = agent_factory(**self.creator)
        if self.proxy and isinstance(self.proxy, dict):
            self.proxy = agent_factory(**self.proxy)
        self.status = Status(self.status)

    def is_rejected(self) -> bool:
        return self.status == Status.REJECTED

    def is_accepted(self) -> bool:
        return self.status == Status.ACCEPTED

    def is_pending(self) -> bool:
        return self.status == Status.PENDING
