"""
Provides quality-assurance annotations for the submission & moderation system.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, Union, List, Dict, Type, Any, Literal

from arxiv.taxonomy.category import Category
from mypy_extensions import TypedDict
from pydantic import AwareDatetime, BaseModel, Field

from .agent import Agent


class Comment(BaseModel):
    """A freeform textual annotation."""

    event_id: str
    creator: Agent
    created: AwareDatetime
    proxy: Optional[Agent] = None
    body: str


# ClassifierResult = TypedDict('ClassifierResult',
#                              {'category': Category, 'probability': float})
class ClassifierResult(BaseModel):
    category: Category
    probability: float

class Annotation(BaseModel):
    event_id: str
    creator: Agent
    created: AwareDatetime


class ClassifierResults(Annotation):
    """Represents suggested classifications from an auto-classifier."""
    proxy: Optional[Agent] = None
    classifier: Literal["classic", "pg"] = "classic"
    results: List[ClassifierResult]
    annotation_type: str = Field(default='ClassifierResults')


class Feature(Annotation):
    """Represents features drawn from the content of the submission."""
    feature_type: Literal["chars", "pages", "stops", "words", "%stop"]
    proxy: Optional[Agent] = None
    feature_value: Union[int, float] = Field(default=0)
    annotation_type: str = Field(default='Feature')
