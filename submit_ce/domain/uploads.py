"""Upload-related data structures."""

from typing import List, Optional
from datetime import datetime
from enum import Enum

from pydantic import BaseModel
from yarl import URL

from .submission import SubmissionContent


class FileErrorLevels(Enum):
    """Error severities."""

    ERROR = 'ERROR'
    WARNING = 'WARN'


class FileError(BaseModel):
    """Represents an error returned by the file management service."""

    error_type: FileErrorLevels
    message: str
    more_info: Optional[str] = None


class FileStatus(BaseModel):
    """Represents the state of an uploaded file."""

    path: str
    """Path to file relatie to the `submission_src_dir`."""

    name: str

    content_type: str
    """MIME content type."""

    bytes: int
    """File length in bytes."""

    crc32c: str
    """CRC32C checksum.

    CRC32C used due to support in GS."""

    url: URL
    """HTTPS, GS, file or other URL to object.

    This MUST be to a versioned generation of the file if the implementing
    store supports it. """

    is_versioned: bool
    """If this file is versioned in the implementing store."""

    modified: datetime
    ancillary: bool = False
    errors: List[FileError] = []


class UploadStatus(Enum):  # type: ignore
    """The status of the upload workspace with respect to submission."""

    READY = 'READY'
    READY_WITH_WARNINGS = 'READY_WITH_WARNINGS'
    ERRORS = 'ERRORS'

class UploadLifecycleStates(Enum):  # type: ignore
    """The status of the workspace with respect to its lifecycle."""

    ACTIVE = 'ACTIVE'
    RELEASED = 'RELEASED'
    DELETED = 'DELETED'


class Workspace(BaseModel):
    """Represents the state of a submission's file workspace."""

    started: datetime
    completed: datetime
    created: datetime
    modified: datetime
    status: UploadStatus
    lifecycle: UploadLifecycleStates
    locked: bool
    identifier: str
    source_format: SubmissionContent.Format = SubmissionContent.Format.UNKNOWN
    checksum: Optional[str] = None
    size: Optional[int] = None
    """Size in bytes of the uncompressed upload workspace."""
    compressed_size: Optional[int] = None
    """Size in bytes of the compressed upload package."""
    files: List[FileStatus] = []
    errors: List[FileError] = []

    @property
    def file_count(self) -> int:
        """The number of files in the workspace."""
        return len(self.files)
