from typing import Protocol, runtime_checkable
from io import BytesIO

@runtime_checkable
class SubmitFile(Protocol):
    """Represents a file for a submission."""
    filename: str
    """Name of the file as provided by the client."""
    content_type: str
    """The MIME type of the file as provided by the client."""
    stream: BytesIO
    """File contents as provided by the client."""
