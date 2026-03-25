"""Workflow and stages related to new submissions"""

from typing import Callable, List
from . import conditions
from submit_ce.domain import Submission


SubmissionCheck = Callable[[Submission], (bool)]
"""Function type that can be used to check if a submission meets a condition."""


class Stage:
    """Class for workflow stages."""

    endpoint: str
    label: str
    title: str
    display: str
    must_see: bool
    required: bool
    completed: List[SubmissionCheck]

    def __init__(self, required: bool = True, must_see: bool = False) -> None:
        """
        Configure the stage for a particular workflow.
        Parameters
        ----------
        required : bool
            This stage must be complete to proceed.
        must_see : bool
            This stage must be seen (even if already complete) to proceed.
        """
        self.required = required
        self.must_see = must_see

    def is_complete(self, submission: Submission) -> bool:
        return all([fn(submission) for fn in self.completed])

    def incomplete(self, submission: Submission) -> list[str]:
        """Returns names of conditions that caused incomplete, or empty list if completed."""
        return [done_check.__name__ for
                done_check in self.completed
                if not done_check(submission)]


class VerifyUser(Stage):
    """The user is asked to verify their personal information."""

    endpoint = 'verify_user'
    label = 'verify your personal information'
    title = 'Verify user info'
    display = 'Verify User'
    completed = [conditions.is_contact_verified]


class Agreement(Stage):
    """The user is required to agree to arXiv policies."""

    endpoint = 'policy'
    label = 'accept arXiv submission policies'
    title = "Submission Agreement"
    display = "Agreement"
    completed = [conditions.is_policy_accepted]


class License(Stage):
    """The user is asked to select a license."""

    endpoint = 'license'
    label = 'choose a license'
    title = "Use of Author's Work"
    display = "License"
    completed = [conditions.has_license]


class Classification(Stage):
    """The user is asked to select a primary category."""

    endpoint = 'classification'
    label = 'select a primary category'
    title = "Choose category"
    display = "Category"
    completed = [conditions.has_primary]


class FileUpload(Stage):
    """The user is asked to upload files for their submission."""

    endpoint = 'file_upload'
    label = 'upload your submission files'
    title = "File upload"
    display = "Upload Files"
    always_check = True
    completed = [conditions.has_valid_content]


class ReviewFiles(Stage):
    """The user is asked to review files for their submission with input
       from preflight analysis.
    """
    endpoint = 'review_files'
    label = 'review your submission files'
    title = "Review Files"
    display = "Review Files"
    always_check = True
    completed = [conditions.has_primary]

class Process(Stage):
    """Uploaded files are processed; this is primarily to compile LaTeX."""

    endpoint = 'file_process'
    label = 'process your submission files'
    title = "File process"
    display = "Process Files"
    """We need to re-process every time the source is updated."""
    completed = [conditions.is_source_processed]


class Metadata(Stage):
    """The user is asked to require core metadata fields, like title."""

    endpoint = 'add_metadata'
    label = 'add required metadata'
    title = "Add metadata"
    display = "Metadata"
    completed = [conditions.is_metadata_complete]


class OptionalMetadata(Stage):
    """The user is given the option of entering optional metadata."""

    endpoint = 'add_optional_metadata'
    label = 'add optional metadata'
    title = "Add optional metadata"
    display = "Opt. Metadata"
    completed = [conditions.is_opt_metadata_complete]


class FinalPreview(Stage):
    """The user is asked to review the submission before finalizing."""

    endpoint = 'final_preview'
    label = 'preview and approve your submission'
    title = "Final preview"
    display = "Preview"
    completed = [conditions.is_finalized]


class Confirm(Stage):
    """The submission is confirmed."""

    endpoint = 'confirmation'
    label = 'your submission is confirmed'
    title = "Submission confirmed"
    display = "Confirmed"
    completed = [lambda _:False]
