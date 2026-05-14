from __future__ import annotations
from pydantic import ConfigDict, Field, WithJsonSchema
from typing import TYPE_CHECKING, List, Annotated, Optional

if TYPE_CHECKING:
    from submit_ce.api.submit import SubmitApi

from . import validators
from .base import Event, EventWithSideEffect
from ..submission import Submission
from ..uploads import SourceFormat, SubmitFile
from ..exceptions import InvalidEvent

import logging
logger = logging.getLogger(__name__)

def _common_file_change_project(submission: Submission) -> None:
    """Common changes to submission when any file change happens."""
    submission.submitter_confirmed_preview = False


class UploadArchive(EventWithSideEffect):
    """Uploads a zip or tgz file to the workspace, unpacking all the files."""

    NAME = "upload and unpack archive"
    NAMED = "archive unpacked and added"

    file: Annotated[SubmitFile, WithJsonSchema({'type': 'object'})] = Field(exclude=True)
    """File to upload."""

    uncompressed_size: int = 0

    def validate(self, submission: Submission) -> None:
        validators.submission_is_not_finalized(self, submission)

    def execute(self, api: SubmitApi, submission: Submission) -> None:
        """Upload the new files using the file store."""
        api.get_file_store().store_source_package(str(submission.submission_id), self.file, 4098)
        workspace = api.get_file_store().get_workspace(str(submission.submission_id))
        if workspace is None:
            raise RuntimeError("Workspace was None during UploadArchive")
        elif workspace.size and workspace.size > 0:
            self.uncompressed_size = workspace.size
        else:
            self.uncompressed_size = 0

    def project(self, submission: Submission) -> Submission:
        submission.uncompressed_size = self.uncompressed_size
        _common_file_change_project(submission)
        return submission


class UploadFiles(EventWithSideEffect):
    """Add files to the upload workspace for this submission.

    Also initializes the upload package if none exists yet.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    NAME = "add files"
    NAMED = "files added"

    files: List[Annotated[SubmitFile, WithJsonSchema({'type': 'object'})]] = \
        Field(default_factory=list, exclude=True)
    bytes_added: int = 0

    def validate(self, submission: Submission) -> None:
        validators.submission_is_not_finalized(self, submission)

    def execute(self, api: SubmitApi, submission: Submission) -> None:
        """Upload the new files using the file store."""
        file_store = api.get_file_store()
        for f in self.files:
            stat=file_store.store_source_file(str(submission.submission_id), f, chunk_size=4096)
            self.bytes_added += stat.bytes

    def project(self, submission: Submission) -> Submission:
        submission.uncompressed_size = submission.uncompressed_size + self.bytes_added
        _common_file_change_project(submission)
        return submission


class RemoveFiles(EventWithSideEffect):
    """Remove files from the upload workspace for this submission."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    NAME = "remove files"
    NAMED = "files removed"

    files: List[Annotated[SubmitFile, WithJsonSchema({'type': 'object'})]] = \
        Field(default_factory=list, exclude=True)

    bytes_removed:int = 0

    def validate(self, submission: Submission) -> None:
        validators.submission_is_not_finalized(self, submission)

    def execute(self, api: SubmitApi, submission: Submission) -> None:
        """Remove the specified files from the file store."""
        file_store = api.get_file_store()
        for f in self.files:
            file_store.delete_source_file(str(submission.submission_id), f.filename)
            # TODO Will need to accumulate the size of the files removed and update the uncompressed_size
            # self.bytes_removed += f.size Not surehow to get size!

    def project(self, submission: Submission) -> Submission:
        #submission.uncompressed_size = submission.uncompressed_size - self.bytes_removed
        submission.submitter_confirmed_preview = False
        return submission


class RemoveAllFiles(EventWithSideEffect):
    """Remove all files from the upload workspace for this submission."""

    NAME = "remove all files"
    NAMED = "all files removed"

    def validate(self, submission: Submission) -> None:
        validators.submission_is_not_finalized(self, submission)

    def execute(self, api: SubmitApi, submission: Submission) -> None:
        """Remove the entire upload workspace using the file store."""
        file_store = api.get_file_store()
        file_store.delete_all_source_files(str(submission.submission_id))
        file_store.delete_preview(str(submission.submission_id))

    def project(self, submission: Submission) -> Submission:
        submission.source_format = None
        submission.uncompressed_size = 0
        _common_file_change_project(submission)
        return submission
