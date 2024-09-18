from __future__ import annotations

import pprint
from typing import Optional, Any, Dict, Literal

from pydantic import BaseModel, AwareDatetime, StrictStr

from submit_ce.submit_fastapi.api.models.agent import Agent


class BaseEvent(BaseModel):
    event_info: EventInfo


    def to_str(self) -> str:
        """Returns the string representation of the model using alias"""
        return pprint.pformat(self.model_dump(by_alias=True))


    def to_dict(self) -> Dict[str, Any]:
        """Return the dictionary representation of the model using alias.

        This has the following differences from calling pydantic's
        `self.model_dump(by_alias=True)`:

        * `None` is only added to the output dict for nullable fields that
          were set at model initialization. Other fields with value `None`
          are ignored.
        """
        _dict = self.model_dump(
            by_alias=True,
            exclude={
            },
            exclude_none=True,
        )
        return _dict


class EventInfo(BaseModel):
    event_id: str
    submission_id: str
    user: Agent
    """
    The agent responsible for the operation represented by this event.

    This may be any type of agent. 
    
    This is **not** necessarily the creator of the submission.
    """

    recorded: Optional[AwareDatetime]
    """
    When the event was originally recorded in the system. 
    
    Must have a timezone.
    """

    proxy: Optional[Agent]
    """
    The agent who facilitated the operation on behalf of the :attr:`.creator`.

    This may be an API client, or another user who has been designated as a
    proxy. Note that proxy implies that the creator was not directly involved.
    """

    client: Optional[Agent]
    """
    The client through which the :attr:`.creator` performed the operation.

    If the creator was directly involved in the operation, this property should
    be the client that facilitated the operation.
    """


class AgreedToPolicy(BaseEvent):
    """
    The sender of this request agrees to the statement in the agreement.
    """
    accepted_policy: StrictStr


class StartedNew(BaseModel):
    """
    Starts a submission.
    """
    submission_type: Literal["new"]
    """What does the submission change in the system?
    
    `new`: deposit a new item or paper as version 1.
    `replacement`: deposit a version that supersedes the latest version on an existing paper.
    `withdrawal`: mark a version of a paper as no longer valid.
    `cross`: add a category to an existing paper.
    `jref`: add a jref to an existing paper.
    """


class StartedAlterExising(BaseModel):
    """
    Starts a submission.
    """
    submission_type: Literal["replacement", "withdrawal", "cross", "jref"]
    """What does the submission change in the system?

    `new`: deposit a new item or paper as version 1.
    `replacement`: deposit a version that supersedes the latest version on an existing paper.
    `withdrawal`: mark a version of a paper as no longer valid.
    `cross`: add a category to an existing paper.
    `jref`: add a jref to an existing paper.
    """

    paperid: str
    """The existing paper that is modified. Only valid for replacement, withdrawal, and jref and cross"""

