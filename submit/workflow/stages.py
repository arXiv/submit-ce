"""Workflow and stages related to new submissions"""

from typing import Iterable, Optional, Callable, List, Iterator
from . import conditions
from arxiv.submission.domain import Submission


SubmissionCheck = Callable[[Submission], (bool)]
"""Function type that can be used to check if a ui-app meets
   a condition."""


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


class VerifyUser(Stage):
    """The user is asked to verify their personal information."""

    endpoint = 'verify_user'
    label = 'verify your personal information'
    title = 'Verify user info'
    display = 'Verify User'
    completed = [conditions.is_contact_verified]


class Authorship(Stage):
    """The user is asked to verify their authorship status."""

    endpoint = 'authorship'
    label = 'confirm authorship'
    title = "Confirm authorship"
    display = "Authorship"
    completed = [conditions.is_authorship_indicated]


class License(Stage):
    """The user is asked to select a license."""

    endpoint = 'license'
    label = 'choose a license'
    title = "Choose license"
    display = "License"
    completed = [conditions.has_license]


class Policy(Stage):
    """The user is required to agree to arXiv policies."""

    endpoint = 'policy'
    label = 'accept arXiv ui-app policies'
    title = "Acknowledge policy"
    display = "Policy"
    completed = [conditions.is_policy_accepted]


class Classification(Stage):
    """The user is asked to select a primary category."""

    endpoint = 'classification'
    label = 'select a primary category'
    title = "Choose category"
    display = "Category"
    completed = [conditions.has_primary]


class CrossList(Stage):
    """The user is given the option of selecting cross-list categories."""

    endpoint = 'cross_list'
    label = 'add cross-list categories'
    title = "Add cross-list"
    display = "Cross-list"
    completed = [conditions.has_secondary]


class FileUpload(Stage):
    """The user is asked to upload files for their ui-app."""

    endpoint = 'file_upload'
    label = 'upload your ui-app files'
    title = "File upload"
    display = "Upload Files"
    always_check = True
    completed = [conditions.has_valid_content]


class Process(Stage):
    """Uploaded files are processed; this is primarily to compile LaTeX."""

    endpoint = 'file_process'
    label = 'process your ui-app files'
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
    """The user is asked to review the ui-app before finalizing."""

    endpoint = 'final_preview'
    label = 'preview and approve your ui-app'
    title = "Final preview"
    display = "Preview"
    completed = [conditions.is_finalized]


class Confirm(Stage):
    """The ui-app is confirmed."""

    endpoint = 'confirmation'
    label = 'your ui-app is confirmed'
    title = "Submission confirmed"
    display = "Confirmed"
    completed = [lambda _:False]

