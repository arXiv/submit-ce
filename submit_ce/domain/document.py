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

import copy
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from arxiv.license import LICENSES

from .agent import Client, User
from .meta import Classification, License
from .submission import Submission, SubmissionMetadata


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

    @property
    def display_metadata(self) -> Optional[DocMetadata]:
        """Metadata for the current version, from whichever source has it.

        :attr:`current_metadata` for a paper that legacy has written
        ``arXiv_metadata`` for, standing in from the announced submission
        otherwise (see :attr:`latest_announced_submission`). What to show a user
        about a paper, and the same rule :meth:`seed_submission` builds from.
        """
        return self.current_metadata or self._metadata_from_announced()

    @property
    def latest_announced_submission(self) -> Optional[Submission]:
        """The announced submission for the highest announced version.

        The fallback source for a paper's announced state. ``arXiv_metadata``
        and ``arXiv_document_category`` are written by the legacy publish
        pipeline, not by this system, so a paper announced here may have
        neither -- but it always has an announced submission row.
        """
        announced = [s for s in self.submissions
                     if s.status == Submission.ANNOUNCED]
        if not announced:
            return None
        return max(announced, key=lambda s: s.version)

    def _metadata_from_announced(self) -> Optional[DocMetadata]:
        """Stand-in :class:`.DocMetadata` built from the announced submission.

        Used when the paper has no ``arXiv_metadata`` row, so that a new
        submission is not seeded with an empty title and abstract. See
        :attr:`latest_announced_submission`.
        """
        latest = self.latest_announced_submission
        if latest is None:
            return None
        md = latest.metadata
        return DocMetadata(
            version=latest.version,
            title=md.title,
            abstract=md.abstract,
            authors=md.authors_display,
            comments=md.comments,
            report_num=md.report_num,
            journal_ref=md.journal_ref,
            doi=md.doi,
            msc_class=md.msc_class,
            acm_class=md.acm_class,
            license=latest.license.uri if latest.license else None,
            is_current=True)

    def seed_submission(self, creator: User,
                        client: Optional[Client] = None) -> Submission:
        """Build a :class:`.Submission` from a paper's announced state.

        This is the ``before`` state that events creating a new submission
        against an announced paper (a journal reference, a replacement, a
        withdrawal) project from. It reproduces what legacy calls
        ``fields_for_submission``: the fields of the *current*
        :class:`.DocMetadata` version, plus the paper's current
        classifications.

        Deliberately **not** seeded, matching legacy:

        - ``source_format`` / ``uncompressed_size`` / ``is_oversize`` --
          ``fields_for_submission`` does not copy the source fields, which is
          why the format and oversize auto-holds are no-ops on a journal
          reference.
        - Moderation state (holds, waivers, flags, comments, proposals,
          requests) belongs to the submission that carried it, not the paper.

        ``creator`` is the user making the new submission, not the original
        submitter; the classic row's submitter is projected from it.
        """
        md = self.display_metadata
        license: Optional[License] = None
        if md is not None and md.license:
            label = LICENSES.get(md.license, {}).get('label')
            license = License(uri=md.license, name=label)

        # Current categories come from arXiv_document_category; fall back to the
        # announced submission's when the paper has no rows there.
        primary = self.primary_classification
        secondaries = self.secondary_classification
        if primary is None:
            latest = self.latest_announced_submission
            if latest is not None:
                primary = latest.primary_classification
                secondaries = latest.secondary_classification

        return Submission(
            creator=creator,
            owner=creator,
            client=client,
            arxiv_id=self.paper_id,
            version=md.version if md is not None else self.latest_version,
            status=Submission.ANNOUNCED,  # TODO is this what legacy does or should this be WORKING?
            created=self.created,  # TODO Is this what legacy does or should this be now?
            license=license,
            primary_classification=copy.deepcopy(primary),
            secondary_classification=copy.deepcopy(secondaries),
            metadata=SubmissionMetadata(
                title=md.title if md else None,
                abstract=md.abstract if md else None,
                authors_display=(md.authors or '') if md else '',
                comments=(md.comments or '') if md else '',
                report_num=md.report_num if md else None,
                journal_ref=md.journal_ref if md else None,
                doi=md.doi if md else None,
                msc_class=md.msc_class if md else None,
                acm_class=md.acm_class if md else None,
            ),
        )
