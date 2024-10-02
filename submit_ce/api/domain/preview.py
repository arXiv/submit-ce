"""Provides :class:`.Preview`."""
from pydantic import BaseModel, AwareDatetime


class Preview(BaseModel):
    """Metadata about a submission preview."""

    source_id: int
    """Identifier of the source from which the preview was generated."""

    source_checksum: str
    """Checksum of the source from which the preview was generated."""

    preview_checksum: str
    """Checksum of the preview content itself."""

    size_bytes: int
    """Size (in bytes) of the preview content."""

    added: AwareDatetime
    """The datetime when the preview was deposited."""
