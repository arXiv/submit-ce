"""Metadata objects in support of submissions."""
from __future__ import annotations

from arxiv.taxonomy.definitions import CATEGORIES
from pydantic import BaseModel, Field
from pydantic.dataclasses import dataclass
from typing import Optional, Literal, List

ACTIVE_CATEGORY = Literal[tuple(cat.id for cat in CATEGORIES.values() if cat.is_active)]
ALL_CATEGORIES = Literal[tuple(cat.id for cat in CATEGORIES.values())]


@dataclass
class Classification:
    """A classification for a :class:`.domain.submission.Submission`."""

    category: ACTIVE_CATEGORY


@dataclass
class License:
    """A license for distribution of the submission."""

    uri: str
    name: Optional[str] = None


class CategoryChange(BaseModel):
    new_primary: Optional[ALL_CATEGORIES] = None
    """The primary category before this change"""
    old_primary: Optional[ALL_CATEGORIES] = None
    """The primary category after this change"""
    new_secondaries: List[ALL_CATEGORIES] = Field(default_factory=list)
    """The secondaries after this change"""
    old_secondaries: List[ALL_CATEGORIES] = Field(default_factory=list)
    """The secondaries before this change"""
