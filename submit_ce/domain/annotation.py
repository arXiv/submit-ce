"""
Provides quality-assurance annotations for the submission & moderation system.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, Union, List, Dict, Type, Any

from .agent import User

from pydantic import BaseModel

class Comment(BaseModel):
    """A freeform textual annotation."""

    event_id: str
    creator: User
    created: datetime
    proxy: Optional[User]
    body: str


class ClassifierResult(BaseModel):
    category: str
    probability: float


class Annotation(BaseModel):
    event_id: str
    creator: User
    created: datetime


class ClassifierResults(Annotation):
    """Represents suggested classifications from an auto-classifier."""

    class Classifiers(Enum):
        """Supported classifiers."""

        CLASSIC = "classic"

    # event_id: str
    # creator: Agent
    # created: datetime
    proxy: Optional[User]
    classifier: Classifiers
    results: List[ClassifierResult]
    annotation_type: str ='ClassifierResults'



class Feature(Annotation):
    """Represents features drawn from the content of the submission."""

    class Type(Enum):
        """Supported features."""

        CHARACTER_COUNT = "chars"
        PAGE_COUNT = "pages"
        STOPWORD_COUNT = "stops"
        STOPWORD_PERCENT = "%stop"
        WORD_COUNT = "words"

    # event_id: str
    # created: datetime
    # creator: Agent
    feature_type: Type
    proxy: Optional[User]
    feature_value: Union[int, float] = 0
    annotation_type: str = 'Feature'


annotation_types: Dict[str, Type[Annotation]] = {
    'Feature': Feature,
    'ClassifierResults': ClassifierResults
}


def annotation_factory(**data: Any) -> Annotation:
    an: Annotation = annotation_types[data.pop('annotation_type')](**data)
    return an
