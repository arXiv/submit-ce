from __future__ import annotations
from pydantic import ConfigDict, Field, WithJsonSchema
from typing import TYPE_CHECKING, List, Annotated, Optional

if TYPE_CHECKING:
    from submit_ce.api.submit import SubmitApi

from . import validators
from .base import EventWithSideEffect
from ..submission import Submission
from ..uploads import SubmitFile

import logging
logger = logging.getLogger(__name__)

def _common_file_change_project(submission: Submission) -> None:
    """Common changes during `project` to submission when any file change happens."""
    submission.submitter_confirmed_preview = False


def _common_file_change_execute(api: SubmitApi, submission: Submission) -> None:
    """Common changes during `execute` when any file change happens."""
    file_store = api.get_file_store()
    file_store.delete_preflight(str(submission.submission_id))
    file_store.delete_preview(str(submission.submission_id))


class UploadArchive(EventWithSideEffect):
    """Uploads a zip or tgz file to the workspace, unpacking all the files."""

    NAME = "upload and unpack archive"
    NAMED = "archive unpacked and added"

    file: Optional[Annotated[SubmitFile, WithJsonSchema({'type': 'object'})]] = Field(default=None, exclude=True)
    """File to upload. Excluded from serialization, so `None` after replay from event history."""

    bytes_added: int = 0
    """Bytes added by uploading this archive."""

    def validate(self, submission: Submission) -> None:
        validators.submission_is_not_finalized(self, submission)

    def execute(self, api: SubmitApi, submission: Submission) -> None:
        """Upload the new files using the file store."""
        files = api.get_file_store().store_source_package(str(submission.submission_id), self.file, 4098)
        self.bytes_added = sum([file.bytes for file in files])
        _common_file_change_execute(api, submission)

    def project(self, submission: Submission) -> Submission:
        submission.uncompressed_size += self.bytes_added
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
        _common_file_change_execute(api, submission)

    def project(self, submission: Submission) -> Submission:
        submission.uncompressed_size += self.bytes_added
        _common_file_change_project(submission)
        return submission


class RemoveFiles(EventWithSideEffect):
    """Remove files from the upload workspace for this submission."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    NAME = "remove files"
    NAMED = "files removed"

    files: List[str] = Field(default_factory=List)
    """name of files to remove."""

    bytes_removed:int = 0
    """Bytes removed by removing these files."""

    def validate(self, submission: Submission) -> None:
        validators.submission_is_not_finalized(self, submission)

    def execute(self, api: SubmitApi, submission: Submission) -> None:
        """Remove the specified files from the file store."""

        file_store = api.get_file_store()
        for filename in self.files:
            file = file_store.delete_source_file(str(submission.submission_id), filename)
            if file:
                self.bytes_removed += file.bytes

        _common_file_change_execute(api, submission)

    def project(self, submission: Submission) -> Submission:
        submission.uncompressed_size -= self.bytes_removed
        _common_file_change_project(submission)
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
        _common_file_change_execute(api, submission)

    def project(self, submission: Submission) -> Submission:
        submission.source_format = None
        submission.uncompressed_size = 0
        _common_file_change_project(submission)
        return submission
