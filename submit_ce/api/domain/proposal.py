"""
Proposals provide a mechanism for suggesting changes to submissions.

The primary use-case in the classic submission & moderation system is for
suggesting changes to the primary or cross-list classification. Such proposals
are generated both automatically based on the results of the classifier and
manually by moderators.
"""
from dataclasses import field
from datetime import datetime
from enum import Enum
from typing import Optional, List

from pydantic import BaseModel, AwareDatetime, Field, ImportString

from .agent import Agent
from .annotation import Comment
from .util import get_tzaware_utc_now


class Proposal(BaseModel):
    """Represents a proposal to apply an event to a submission."""

    class ProposalStatus(Enum):
        PENDING = 'pending'
        REJECTED = 'rejected'
        ACCEPTED = 'accepted'

    event_id: str
    creator: Agent
    created: AwareDatetime = Field(default_factory=get_tzaware_utc_now)
    # scope: str      # TODO: document this.
    proxy: Optional[Agent] = field(default=None)

    proposed_event_type: Optional[ImportString] = field(default=None)
    proposed_event_data: dict = field(default_factory=dict)
    comments: List[Comment] = field(default_factory=list)
    status: ProposalStatus = field(default=ProposalStatus.PENDING)

    @property
    def proposal_type(self) -> str:
        """Name (str) of the type of annotation."""
        assert self.proposed_event_type is not None
        return self.proposed_event_type.__name__

    def is_rejected(self) -> bool:
        return self.status == self.ProposalStatus.REJECTED

    def is_accepted(self) -> bool:
        return self.status == self.ProposalStatus.ACCEPTED

    def is_pending(self) -> bool:
        return self.status == self.ProposalStatus.PENDING
