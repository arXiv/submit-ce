"""Metadata objects in support of submissions."""

from pydantic.dataclasses import dataclass
from typing import Optional

from arxiv.taxonomy.category import Category


@dataclass
class Classification:
    """A classification for a :class:`.domain.submission.Submission`."""

    category: Category


@dataclass
class License:
    """A license for distribution of the submission."""

    uri: str
    name: Optional[str] = None
