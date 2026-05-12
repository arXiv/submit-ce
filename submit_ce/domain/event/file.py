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


class UploadArchive(EventWithSideEffect):
    """Uploads a zip or tgz file to the workspace, unpacking all the files."""

    NAME = "upload and unpack archive"
    NAMED = "archive unpacked and added"

    file: Annotated[SubmitFile, WithJsonSchema({'type': 'object'})] = Field(default_factory=list, exclude=True)
    """File to upload."""

    uncompressed_size: int = 0

    def validate(self, submission: Submission) -> None:
        validators.submission_is_not_finalized(self, submission)

    def execute(self, api: SubmitApi, submission: Submission) -> None:
        """Upload the new files using the file store."""
        file_store = api.get_file_store()
        # TODO the unpack of the archive is not written
        for f in self.files:
            file_store.store_source_file(str(submission.submission_id), f, chunk_size=4096)

    def project(self, submission: Submission) -> Submission:
        submission.uncompressed_size = self.uncompressed_size
        submission.submitter_confirmed_preview = False
        return submission


class AddFiles(EventWithSideEffect):
    """Add files to the upload workspace for this submission.

    Also initializes the upload package if none exists yet.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    NAME = "add files"
    NAMED = "files added"

    files: List[Annotated[SubmitFile, WithJsonSchema({'type': 'object'})]] = Field(default_factory=list, exclude=True)
    uncompressed_size: int = 0
    source_format: SourceFormat = Field(default=SourceFormat.UNKNOWN)

    def model_post_init(self, *args, **kwargs) -> None:
        if type(self.source_format) is str:
            self.source_format = SourceFormat(self.source_format)

    def validate(self, submission: Submission) -> None:
        validators.submission_is_not_finalized(self, submission)

    def execute(self, api: SubmitApi, submission: Submission) -> None:
        """Upload the new files using the file store."""
        file_store = api.get_file_store()
        for f in self.files:
            file_store.store_source_file(str(submission.submission_id), f, chunk_size=4096)

    def project(self, submission: Submission) -> Submission:
        submission.source_format = self.source_format
        submission.uncompressed_size = self.uncompressed_size
        submission.submitter_confirmed_preview = False
        return submission


class RemoveFiles(EventWithSideEffect):
    """Remove files from the upload workspace for this submission."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    NAME = "remove files"
    NAMED = "files removed"

    files: List[Annotated[SubmitFile, WithJsonSchema({'type': 'object'})]] = Field(default_factory=list, exclude=True)
    uncompressed_size: int = 0

    def validate(self, submission: Submission) -> None:
        validators.submission_is_not_finalized(self, submission)

    def execute(self, api: SubmitApi, submission: Submission) -> None:
        """Remove the specified files from the file store."""
        file_store = api.get_file_store()
        for f in self.files:
            file_store.delete_source_file(str(submission.submission_id), f.filename)

    def project(self, submission: Submission) -> Submission:
        submission.uncompressed_size = self.uncompressed_size
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
        submission.submitter_confirmed_preview = False
        return submission
