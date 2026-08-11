"""Metadata objects in support of submissions."""

from typing import Optional
from dataclasses import dataclass


@dataclass
class Classification:
    """A classification for a :class:`.domain.submission.Submission`."""

    category: str

    is_published: bool = False
    """Whether this category is already announced on the paper.

    Mirrors classic ``arXiv_submission_category.is_published``. A submission
    seeded from an announced paper (see
    :meth:`.domain.document.Document.seed_submission`) carries the paper's
    current categories as published; a category the submission is *adding* --
    notably a cross-list -- is unpublished until the publish run announces it.
    """

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
