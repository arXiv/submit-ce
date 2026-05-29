from typing import List

from submit_ce.domain import Submission, Event
from submit_ce.domain.event.process import StartDirectives
from submit_ce.domain.uploads import SourceFormat


def is_contact_verified(submission: Submission, events: List[Event]) -> bool:
    """Determine whether the submitter has verified their information."""
    return submission.submitter_contact_verified is True


def is_authorship_indicated(submission: Submission, events: List[Event]) -> bool:
    """Determine whether the submitter has indicated authorship."""
    return submission.submitter_is_author is not None


def has_license(submission: Submission, events: List[Event]) -> bool:
    """Determine whether the submitter has selected a license."""
    return submission.license is not None


def is_policy_accepted(submission: Submission, events: List[Event]) -> bool:
    """Determine whether the submitter has accepted arXiv policies."""
    return submission.submitter_accepts_policy is True


def has_primary(submission: Submission, events: List[Event]) -> bool:
    """Determine whether the submitter selected a primary category."""
    return submission.primary_classification is not None


def has_secondary(submission: Submission, events: List[Event]) -> bool:
    return len(submission.secondary_classification) > 0


def has_abstract(submission: Submission, events: List[Event]) -> bool:
    return bool(submission.metadata.abstract)

def has_comment(submission: Submission, events: List[Event]) -> bool:
    return bool(submission.metadata.comments)

def has_files(submission: Submission, events: List[Event]) -> bool:
    """Determine if the submission has any files."""
    return submission.uncompressed_size > 0

def has_valid_content(submission: Submission, events: List[Event]) -> bool:
    """Determine whether the submitter has uploaded files."""
    return (submission.source_format is not None
            and submission.source_format != SourceFormat.INVALID
            and submission.uncompressed_size > 0)

def has_non_processing_content(submission: Submission, events: List[Event]) -> bool:
    return (submission.source_format is not None
            and submission.source_format != SourceFormat.TEX
            and submission.source_format != SourceFormat.POSTSCRIPT)

def is_source_processed(submission: Submission, events: List[Event]) -> bool:
    """Determine whether the submitter has compiled their upload."""
    return has_valid_content(submission, events) and \
        (submission.is_source_processed or has_non_processing_content(submission, events))


def is_metadata_complete(submission: Submission, events: List[Event]) -> bool:
    """Determine whether the submitter has entered required metadata."""
    return (submission.metadata.title is not None
            and submission.metadata.abstract is not None
            and submission.metadata.authors_display is not None)


def is_opt_metadata_complete(submission: Submission, events: List[Event]) -> bool:
    """Determine whether the user has set optional metadata fields."""
    return (submission.metadata.doi is not None
            or submission.metadata.msc_class is not None
            or submission.metadata.acm_class is not None
            or submission.metadata.report_num is not None
            or submission.metadata.journal_ref is not None)


def is_finalized(submission: Submission, events: List[Event]) -> bool:
    """Determine whether the submission is finalized."""
    return bool(submission.is_finalized)


def has_directives_started(submission: Submission, events: List[Event]) -> bool:
    """Determine whether a StartDirectives event has been dispatched.

    Directives generation is a side-effect of the review-files stage:
    when the user advances past review, a `StartDirectives` event is
    saved and the compile service writes `directives.json`. The event
    history is the authoritative record that this happened.
    """
    return any(isinstance(e, StartDirectives) for e in events)
