from __future__ import annotations

from typing import Literal, List, Optional

from arxiv.taxonomy.definitions import CATEGORIES
from pydantic import BaseModel, Field

from .submission import Submission, Author, SubmissionMetadata, SubmissionContent
from .agent import User, Agent, Automation, Client

ACTIVE_CATEGORY = Literal[tuple(cat.id for cat in CATEGORIES.values() if cat.is_active)]
ALL_CATEGORIES = Literal[tuple(cat.id for cat in CATEGORIES.values())]

class CategoryChangeResult(BaseModel):
    new_primary: Optional[ALL_CATEGORIES] = None
    """The primary category before this change"""
    old_primary: Optional[ALL_CATEGORIES] = None
    """The primary category after this change"""
    new_secondaries: List[ALL_CATEGORIES] = Field(default_factory=list)
    """The secondaries after this change"""
    old_secondaries: List[ALL_CATEGORIES] = Field(default_factory=list)
    """The secondaries before this change"""

