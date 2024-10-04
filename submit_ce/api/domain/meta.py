"""Metadata objects in support of submissions."""

from typing import Optional
from dataclasses import dataclass


@dataclass
class Classification:
    """A classification for a :class:`.domain.submission.Submission`."""

    category: str


@dataclass
class License:
    """An license for distribution of the submission."""

    uri: str
    name: Optional[str] = None
