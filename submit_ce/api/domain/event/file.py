from dataclasses import field


from . import validators
from .base import Event
from ..submission import Submission, SubmissionContent
from ...exceptions import InvalidEvent

import logging
logger = logging.getLogger(__name__)


class SetUploadPackage(Event):
    """Set the upload workspace for this submission."""

    NAME = "set the upload package"
    NAMED = "upload package set"

    identifier: str = field(default_factory=str)
    checksum: str = field(default_factory=str)
    uncompressed_size: int = field(default=0)
    compressed_size: int = field(default=0)
    source_format: SubmissionContent.Format = \
        field(default=SubmissionContent.Format.UNKNOWN)

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

    checksum: str = field(default_factory=str)
    uncompressed_size: int = field(default=0)
    compressed_size: int = field(default=0)
    source_format: SubmissionContent.Format = \
        field(default=SubmissionContent.Format.UNKNOWN)

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
