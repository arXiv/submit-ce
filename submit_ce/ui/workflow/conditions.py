from submit_ce.ui.domain import Submission, SubmissionContent


def is_contact_verified(submission: Submission) -> bool:
    """Determine whether the submitter has verified their information."""
    return submission.submitter_contact_verified is True


def is_authorship_indicated(submission: Submission) -> bool:
    """Determine whether the submitter has indicated authorship."""
    return submission.submitter_is_author is not None


def has_license(submission: Submission) -> bool:
    """Determine whether the submitter has selected a license."""
    return submission.license is not None


def is_policy_accepted(submission: Submission) -> bool:
    """Determine whether the submitter has accepted arXiv policies."""
    return submission.submitter_accepts_policy is True


def has_primary(submission: Submission) -> bool:
    """Determine whether the submitter selected a primary category."""
    return submission.primary_classification is not None


def has_secondary(submission: Submission) -> bool:
    return len(submission.secondary_classification) > 0


def has_valid_content(submission: Submission) -> bool:
    """Determine whether the submitter has uploaded files."""
    return submission.source_content is not None and\
        submission.source_content.checksum is not None and\
        submission.source_content.source_format is not None and \
        submission.source_content.uncompressed_size > 0 and \
        submission.source_content.source_format != SubmissionContent.Format.INVALID

def has_non_processing_content(submission: Submission) -> bool:
    return (submission.source_content is not None and
            submission.source_content.source_format is not None and
            (submission.source_content.source_format != SubmissionContent.Format.TEX
             and
             submission.source_content.source_format != SubmissionContent.Format.POSTSCRIPT))

def is_source_processed(submission: Submission) -> bool:
    """Determine whether the submitter has compiled their upload."""    
    return has_valid_content(submission) and \
        (submission.is_source_processed or has_non_processing_content(submission))


def is_metadata_complete(submission: Submission) -> bool:
    """Determine whether the submitter has entered required metadata."""
    return (submission.metadata.title is not None
            and submission.metadata.abstract is not None
            and submission.metadata.authors_display is not None)


def is_opt_metadata_complete(submission: Submission) -> bool:
    """Determine whether the user has set optional metadata fields."""
    return (submission.metadata.doi is not None
            or submission.metadata.msc_class is not None
            or submission.metadata.acm_class is not None
            or submission.metadata.report_num is not None
            or submission.metadata.journal_ref is not None)


def is_finalized(submission: Submission) -> bool:
    """Determine whether the submission is finalized."""
    return bool(submission.is_finalized)
