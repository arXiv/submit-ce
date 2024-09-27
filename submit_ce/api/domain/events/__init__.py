from __future__ import annotations

import pprint
from typing import Optional, Any, Dict, Literal, List, Union

from pydantic import BaseModel, AwareDatetime

from submit_ce.api.domain import ACTIVE_CATEGORY
from submit_ce.api.domain.agent import User, Client


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
    user: User

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

    proxy: Optional[User]
    """
    The agent who facilitated the operation on behalf of the :attr:`.creator`.

    This may be an API client, or another user who has been designated as a
    proxy. Note that proxy implies that the creator was not directly involved.
    """

    client: Client
    """
    The client through which the :attr:`.creator` performed the operation.

    If the creator was directly involved in the operation, this property should
    be the client that facilitated the operation.
    """


class SetCategories(BaseModel):
    primary_category: ACTIVE_CATEGORY
    """The primary category of research that the submission is relevant to.
    
    A submission must have a primary category and there may be only one primary category for the submission."""

    secondary_categories: List[ACTIVE_CATEGORY]
    """Additional categories of research the submission is relevant to.
    
    This is only for use with new submissions.
    
    The order of these does not have any significance.
    
    There should not be duplications in this list.
    
    The primary category must not be on this list."""


class AgreedToPolicy(BaseModel):
    """
    The sender of this request agrees to the statement in the agreement.
    """
    accepted_policy_id: int
    """The ID of the policy the sender agrees to."""


class SetLicense(BaseModel):
    """
    The sender of this request agrees to offer the submitted items under the statement in the license.
    """
    license_uri: Literal[
        "http://creativecommons.org/licenses/by/4.0/",
        "http://creativecommons.org/licenses/by-sa/4.0/",
        "http://creativecommons.org/licenses/by-nc-sa/4.0/",
        "http://creativecommons.org/licenses/by-nc-nd/4.0/",
        "http://arxiv.org/licenses/nonexclusive-distrib/1.0/",
        "http://creativecommons.org/publicdomain/zero/1.0/",
    ]
    """The license the sender offers to the arxiv users for the submitted items."""

class SetMetadata(BaseModel):
    title: Optional[str] = None
    authors: Optional[str] = None
    comments: Optional[str] = None
    abstract: Optional[str] = None
    report_num: Optional[int] = None
    msc_class: Optional[str] = None
    acm_class: Optional[str] = None
    journal_ref: Optional[str] = None
    doi: Optional[str] = None


class AuthorName(BaseModel):
    """A speculative more detailed author name record."""

    author_list_name: Optional[str] = None
    """Name as it should apper in author list."""

    full_name: Optional[str] = None
    """Full name of the author."""

    language: Optional[str] = None
    """Language of the full name."""

    orcid: Optional[str] = None
    """orcid.org identifier of author"""


class SetAuthorsMetadata(BaseModel):
    authors: List[Union[str, AuthorName]] = None


class SetOrganizationMetadata(BaseModel):
    """A speculative metadata record to describe funding organizations related to the paper."""

    organizations: List[str] = None
    """RORs of funding organizations."""


class AuthorshipDirect(BaseModel):
    """
    Asserts the sender of this request is the author of the submitted items.
    """
    i_am_author: bool
    """By sending `True` the sender asserts they are the author of the submitted items."""

class AuthorshipProxy(BaseModel):
    """
    Asserts that the sender of this request is authorized to deposit the submitted items by the author of the items.
    """
    i_am_authorized_to_proxy: bool
    """By sending `True` the sender asserts they are the authorized proxy of the author of the submitted items."""
    proxy: str
    """Email address of the author of the submitted items."""


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

