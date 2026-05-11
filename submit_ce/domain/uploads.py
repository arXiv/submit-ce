"""Upload-related data structures."""

from typing import Protocol, runtime_checkable, Any
from typing import List, Optional
from datetime import datetime
from enum import Enum

from pydantic import BaseModel
from pydantic_core import core_schema
from yarl import URL


class SourceFormat(Enum):
    """Supported source formats."""

    UNKNOWN = None
    INVALID = "invalid"
    TEX = "tex"
    PDFTEX = "pdftex"
    POSTSCRIPT = "ps"
    HTML = "html"
    PDF = "pdf"


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

    @property
    def size(self):
        return self.bytes

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
    source_format: SourceFormat = SourceFormat.UNKNOWN
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


@runtime_checkable
class SubmitFile(Protocol):
    """Represents a file for a submission.

    This is a protocol to support using a file uploaded to flask to the `SubmitApi`."""
    filename: str
    """Name of the file as provided by the client."""
    content_type: str
    """The MIME type of the file as provided by the client."""
    stream: Any # should be BytesIO but often SpooledTemporaryFile Not sure how to handle this
    """File contents as provided by the client."""

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: Any
    ) -> core_schema.CoreSchema:
        return core_schema.any_schema()


TARGZ_MIMETYPES = frozenset({
    'application/gzip',
    'application/x-gzip',
    'application/x-tar',
    'application/tar+gzip',
    'application/x-compressed',
})
"""tar.gz mime types."""

def is_file_tgz(file: SubmitFile) -> bool:
    """Return True if the uploaded file is a tar.gz archive."""
    return bool(file) and (
        file.content_type in TARGZ_MIMETYPES or
        bool(file.filename and file.filename.endswith('.tar.gz'))
    )
