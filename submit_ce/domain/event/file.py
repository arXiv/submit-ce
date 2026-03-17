from __future__ import annotations
from pydantic import ConfigDict, Field, WithJsonSchema
from typing import TYPE_CHECKING, List, Annotated

if TYPE_CHECKING:
    from submit_ce.api.submit import SubmitApi

from . import validators
from .base import Event, EventWithSideEffect
from ..submission import Submission, SubmissionContent
from ..exceptions import InvalidEvent

from submit_ce.domain.types import SubmitFile

import logging
logger = logging.getLogger(__name__)


class SetUploadPackage(Event):
    """Set the upload workspace for this submission."""

    NAME = "set the upload package"
    NAMED = "upload package set"

    identifier: str = ''
    checksum: str = ''
    uncompressed_size: int = 0
    compressed_size: int = 0
    source_format: SubmissionContent.Format = \
        Field(default=SubmissionContent.Format.UNKNOWN)

    def model_post_init(self, *args, **kwargs) -> None:
        """Make sure that `source_format` is an enum instance."""
        if type(self.source_format) is str:
            self.source_format = SubmissionContent.Format(self.source_format)

    def validate(self, submission: Submission) -> None:
        """Validate data for :class:`.SetUploadPackage`."""
        validators.submission_is_not_finalized(self, submission)

        if not self.identifier:
            raise InvalidEvent(self, 'Missing upload ID')

    def project(self, submission: Submission) -> Submission:
        """Replace :class:`.SubmissionContent` metadata on the submission."""
        submission.source_content = SubmissionContent(
            checksum=self.checksum,
            identifier=self.identifier,
            uncompressed_size=self.uncompressed_size,
            compressed_size=self.compressed_size,
            source_format=self.source_format,
        )
        submission.submitter_confirmed_preview = False
        return submission


class UpdateUploadPackage(Event):
    """Update the upload workspace on this submission."""

    NAME = "update the upload package"
    NAMED = "upload package updated"

    checksum: str = ''
    uncompressed_size: int = 0
    compressed_size: int = 0
    source_format: SubmissionContent.Format = \
        Field(default=SubmissionContent.Format.UNKNOWN)

    def model_post_init(self, *args, **kwargs) -> None:
        """Make sure that `source_format` is an enum instance."""
        if type(self.source_format) is str:
            self.source_format = SubmissionContent.Format(self.source_format)

    def validate(self, submission: Submission) -> None:
        """Validate data for :class:`.SetUploadPackage`."""
        validators.submission_is_not_finalized(self, submission)

    def project(self, submission: Submission) -> Submission:
        """Replace :class:`.SubmissionContent` metadata on the submission."""
        assert submission.source_content is not None
        assert self.source_format is not None
        assert self.checksum is not None
        assert self.uncompressed_size is not None
        assert self.compressed_size is not None
        submission.source_content.source_format = self.source_format
        submission.source_content.checksum = self.checksum
        submission.source_content.uncompressed_size = self.uncompressed_size
        submission.source_content.compressed_size = self.compressed_size
        submission.submitter_confirmed_preview = False
        return submission


class UnsetUploadPackage(Event):
    """Unset the upload workspace for this submission."""

    NAME = "unset the upload package"
    NAMED = "upload package unset"

    def validate(self, submission: Submission) -> None:
        """Validate data for :class:`.UnsetUploadPackage`."""
        validators.submission_is_not_finalized(self, submission)

    def project(self, submission: Submission) -> Submission:
        """Set :attr:`Submission.source_content` to None."""
        submission.source_content = None
        submission.submitter_confirmed_preview = False
        return submission


class AddFiles(EventWithSideEffect):
    """Add files to the upload workspace for this submission."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    NAME = "add files"
    NAMED = "files added"

    files: List[Annotated[SubmitFile, WithJsonSchema({'type': 'object'})]] = Field(default_factory=list, exclude=True)
    checksum: str = ''
    uncompressed_size: int = 0
    compressed_size: int = 0

    def validate(self, submission: Submission) -> None:
        """Validate data for :class:`.AddFiles`."""
        validators.submission_is_not_finalized(self, submission)
        if submission.source_content is None:
            raise InvalidEvent(self, 'No upload package exists for this submission')

    def execute(self, api: SubmitApi, submission: Submission) -> None:
        """Upload the new files using the file store."""
        file_store = api.get_file_store()
        for f in self.files:
            file_store.store_source_file(str(submission.submission_id), f, chunk_size=4096)

    def project(self, submission: Submission) -> Submission:
        """Update :class:`.SubmissionContent` metadata on the submission."""
        assert submission.source_content is not None
        assert self.checksum is not None
        assert self.uncompressed_size is not None
        assert self.compressed_size is not None
        submission.source_content.checksum = self.checksum
        submission.source_content.uncompressed_size = self.uncompressed_size
        submission.source_content.compressed_size = self.compressed_size
        submission.submitter_confirmed_preview = False
        return submission


class RemoveFiles(EventWithSideEffect):
    """Remove files from the upload workspace for this submission."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    NAME = "remove files"
    NAMED = "files removed"

    files: List[Annotated[SubmitFile, WithJsonSchema({'type': 'object'})]] = Field(default_factory=list, exclude=True)
    checksum: str = ''
    uncompressed_size: int = 0
    compressed_size: int = 0

    def validate(self, submission: Submission) -> None:
        """Validate data for :class:`.RemoveFiles`."""
        validators.submission_is_not_finalized(self, submission)
        if submission.source_content is None:
            raise InvalidEvent(self, 'No upload package exists for this submission')

    def execute(self, api: SubmitApi, submission: Submission) -> None:
        """Remove the specified files from the file store."""
        file_store = api.get_file_store()
        for f in self.files:
            file_store.delete_source_file(str(submission.submission_id), f.filename)

    def project(self, submission: Submission) -> Submission:
        """Update :class:`.SubmissionContent` metadata on the submission."""
        assert submission.source_content is not None
        assert self.checksum is not None
        assert self.uncompressed_size is not None
        assert self.compressed_size is not None
        submission.source_content.checksum = self.checksum
        submission.source_content.uncompressed_size = self.uncompressed_size
        submission.source_content.compressed_size = self.compressed_size
        submission.submitter_confirmed_preview = False
        return submission


class RemoveAllFiles(EventWithSideEffect):
    """Remove all files from the upload workspace for this submission."""

    NAME = "remove all files"
    NAMED = "all files removed"

    checksum: str = ''
    uncompressed_size: int = 0
    compressed_size: int = 0

    def validate(self, submission: Submission) -> None:
        """Validate data for :class:`.RemoveAllFiles`."""
        validators.submission_is_not_finalized(self, submission)
        if submission.source_content is None:
            raise InvalidEvent(self, 'No upload package exists for this submission')

    def execute(self, api: SubmitApi, submission: Submission) -> None:
        """Remove the entire upload workspace using the file store."""
        file_store = api.get_file_store()
        file_store.delete_all_source_files(str(submission.submission_id))
        file_store.delete_preview(submission.submission_id)

    def project(self, submission: Submission) -> Submission:
        """Update :class:`.SubmissionContent` metadata on the submission."""
        assert submission.source_content is not None
        assert self.checksum is not None
        assert self.uncompressed_size is not None
        assert self.compressed_size is not None
        submission.source_content.checksum = self.checksum
        submission.source_content.uncompressed_size = self.uncompressed_size
        submission.source_content.compressed_size = self.compressed_size
        submission.submitter_confirmed_preview = False
        return submission
