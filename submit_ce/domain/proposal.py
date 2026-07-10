"""Category proposals on submissions.

A :class:`.Proposal` records a suggested change to a submission's primary or
cross-list classification. In the classic system these are generated both
automatically (based on the classifier) and manually (by moderators), and are
stored in the ``arXiv_submission_category_proposal`` table.

This models proposal *creation* only. Proposal responses (accept/reject) are not
modeled yet, so a freshly created proposal is always
:attr:`ProposalStatus.UNRESOLVED`. The four-value enum mirrors the classic
``proposal_status`` column so that responses can be added later without changing
the on-disk representation.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Optional

from .agent import User


class ProposalStatus(IntEnum):
    """Values mirror the classic ``proposal_status`` column exactly."""

    UNRESOLVED = 0
    ACCEPTED_AS_PRIMARY = 1
    ACCEPTED_AS_SECONDARY = 2
    REJECTED = 3

    UNKNOWN = 404 # to represent an unexpected value from db

@dataclass
class Proposal:
    """A proposed primary or cross-list classification for a submission."""

    proposal_id: str
    """Identifier for the proposal.

    For a proposal created in this session it is the ``event_id`` of the
    proposing event; for one loaded back from the classic database it is the
    classic autoincrement ``proposal_id`` (also kept in
    :attr:`classic_proposal_id`)."""

    category: str
    """The proposed category."""

    is_primary: bool
    """``True`` for a primary proposal, ``False`` for a cross-list proposal."""

    creator: User
    """The agent that made the proposal (a moderator, or the system)."""

    created: Optional[datetime] = field(default=None)
    comment: Optional[str] = field(default=None)
    status: ProposalStatus = field(default=ProposalStatus.UNRESOLVED)

    classic_proposal_id: Optional[int] = field(default=None)
    """The autoincrement ``proposal_id`` from the classic table once persisted."""

    @property
    def is_unresolved(self) -> bool:
        """Whether the proposal is still awaiting a response."""
        return self.status == ProposalStatus.UNRESOLVED
