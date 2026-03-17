"""Metadata objects in support of submissions."""

from typing import Optional
from dataclasses import dataclass


@dataclass
class Classification:
    """A classification for a :class:`.domain.submission.Submission`."""

    category: str

    @property
    def id(self):
        return self.category

    def display(self):
        """Returns a `str` to use to display the category."""
        #TODO Should Classification.dislpay get the full name of the category?
        return self.category


@dataclass
class License:
    """A license for distribution of the submission."""

    uri: str
    name: Optional[str] = None
