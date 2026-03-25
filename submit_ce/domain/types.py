from typing import Protocol, runtime_checkable, Any
from io import BytesIO
from pydantic_core import core_schema


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
