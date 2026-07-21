from typing import Callable, List

from submit_ce.domain import Submission, Event
from submit_ce.domain.event.file import (
    RemoveAllFiles,
    RemoveFiles,
    UploadArchive,
    UploadFiles,
)
from submit_ce.domain.event.process import (
    PreflightStatus,
    StartCompileSource,
    StartDirectives,
    StartPreflight,
)
from submit_ce.domain.uploads import SourceFormat

# Events that mutate the source workspace. Each of these invalidates the
# stored preflight via `_common_file_change_execute` in event/file.py.
_FILE_CHANGE_EVENTS = (UploadArchive, UploadFiles, RemoveFiles, RemoveAllFiles)

# Events that record a preflight run against the current files.
_PREFLIGHT_EVENTS = (StartPreflight, PreflightStatus)

Condition = Callable[[Submission, List[Event]], bool]
"""A workflow condition: true when a stage requirement is satisfied."""


def OR(*conds: Condition) -> Condition:
    """Combine conditions so the result is true when *any* of them is true.

    Short-circuits on the first satisfied condition. With no arguments the
    combined condition is always false (an empty ``or``).
    """
    def combined(submission: Submission, events: List[Event]) -> bool:
        return any(cond(submission, events) for cond in conds)
    return combined


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
    return (submission.uncompressed_size > 0
            and submission.source_format not in [SourceFormat.INVALID, SourceFormat.UNKNOWN]
            )

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


def has_current_directives(submission: Submission, events: List[Event]) -> bool:
    """Determine whether directives are current for the uploaded files.

    Directives generation is a side-effect of the review-files stage:
    when the user advances past review, a `StartDirectives` event is
    saved and the compile service writes `directives.json`. The event
    history is the authoritative record that this happened.

    Any file-change event invalidates the generated directives (see
    `_common_file_change_execute` in event/file.py), so a `StartDirectives`
    only counts if no file-change event has occurred since the most recent
    one. `events` is in chronological order (oldest first).
    """
    if submission.source_format == SourceFormat.PDF:
        return True
    last_directives = None
    for i, event in enumerate(events):
        if isinstance(event, StartDirectives):
            last_directives = i
    if last_directives is None:
        return False
    return not any(isinstance(event, _FILE_CHANGE_EVENTS)
                   for event in events[last_directives + 1:])

def has_compiled_current_source(submission: Submission, events: List[Event]) -> bool:
    """Determine whether a compile has been attempted against the *current* source.

    Used by the Process stage to decide whether compilation needs to be
    (re)triggered on arrival. A compile counts as "current" only if no
    file-change event has occurred since the most recent ``StartCompileSource``:
    any file change invalidates the prior compile (and deletes its preview and
    log via ``_common_file_change_execute`` in event/file.py), so the source
    must be recompiled.

    Returns True when the latest compile is current, meaning no new compile is
    needed. Returns False when there has never been a compile, or when the
    source has changed since the last one -- either way, compilation should be
    initiated. ``events`` is in chronological order (oldest first).

    Note this reflects that a compile was *attempted*, not that it produced a
    usable PDF: a compile that fails on TeX errors still records a
    ``StartCompileSource`` event, so the submitter is shown the failure/log and
    can retry rather than having the Process page silently recompile broken
    source on every refresh. Whether a valid PDF exists is a separate check
    (``does_preview_exist``). [SUBMISSION-75]
    """
    last_compile = None
    for i, event in enumerate(events):
        if isinstance(event, StartCompileSource):
            last_compile = i
    if last_compile is None:
        return False
    return not any(isinstance(event, _FILE_CHANGE_EVENTS)
                   for event in events[last_compile + 1:])


def source_format_pdf(submission: Submission, events: List[Event]) -> bool:
    return submission.source_format == SourceFormat.PDF

def source_format_html(submission: Submission, events: List[Event]) -> bool:
    return submission.source_format == SourceFormat.HTML
