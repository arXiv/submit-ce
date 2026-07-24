"""Domain representation of an announced arXiv paper (document).

A :class:`.Document` is the announced e-print, distinct from a
:class:`.Submission`:

- ``Document`` is the *published paper* -- read-only in this system. It owns the
  arXiv identifier, the per-version metadata history, the current
  classifications, and all submissions ever made against the paper.
- ``Submission`` is *one change* to a document (a new submission, a
  replacement, a withdrawal, a cross-list or a journal reference).

This mirrors the classic split between ``arXiv_documents`` and
``arXiv_submissions``: a document may have several submission rows over its
lifetime, but only the announced ones contribute to its published state.
``Document`` objects are built and read through the
:class:`submit_ce.api.submit.SubmitApi`; nothing here mutates the database.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from .meta import Classification
from .submission import Submission


@dataclass
class DocMetadata:
    """Announced metadata for a single version of a :class:`.Document`.

    Corresponds to one row of the classic ``arXiv_metadata`` table
    (one per ``(paper_id, version)``).
    """

    version: int

    title: Optional[str] = None
    abstract: Optional[str] = None
    authors: Optional[str] = None
    """The canonical arXiv author string."""

    categories: Optional[str] = None
    """Space-delimited category string (``arXiv_metadata.abs_categories``)."""

    comments: Optional[str] = None
    report_num: Optional[str] = None
    msc_class: Optional[str] = None
    acm_class: Optional[str] = None
    journal_ref: Optional[str] = None
    doi: Optional[str] = None
    license: Optional[str] = None

    source_size: Optional[int] = None
    source_format: Optional[str] = None

    submitter_name: Optional[str] = None
    submitter_email: Optional[str] = None
    submitter_id: Optional[int] = None

    created: Optional[datetime] = None
    updated: Optional[datetime] = None

    is_current: bool = False
    is_withdrawn: bool = False


@dataclass
class Document:
    """An announced arXiv paper and all submissions made against it."""

    paper_id: str
    """The canonical announced arXiv identifier, e.g. ``1234.56789``."""

    document_id: Optional[int] = None
    """The classic ``arXiv_documents.document_id``."""

    latest_version: int = 1
    """The highest announced version number."""

    primary_classification: Optional[Classification] = field(default=None)
    secondary_classification: List[Classification] = field(default_factory=list)

    metadata: List[DocMetadata] = field(default_factory=list)
    """Announced metadata, one entry per version, in ascending version order."""

    submitter_email: Optional[str] = field(default=None)
    submitter_id: Optional[int] = field(default=None)
    created: Optional[datetime] = field(default=None)
    """When the paper was first announced."""

    submissions: List[Submission] = field(default_factory=list)
    """All submissions ever made against this paper (new/rep/wdr/cross/jref)."""

    @property
    def active_submissions(self) -> List[Submission]:
        """In-progress (non-announced, non-deleted) submissions on this paper."""
        return [s for s in self.submissions if s.is_active]

    @property
    def has_active_submission(self) -> bool:
        """Whether the paper currently has an in-progress submission."""
        return any(s.is_active for s in self.submissions)

    @property
    def current_metadata(self) -> Optional[DocMetadata]:
        """Metadata for the current (latest announced) version, if any."""
        for md in self.metadata:
            if md.is_current:
                return md
        return self.metadata[-1] if self.metadata else None
