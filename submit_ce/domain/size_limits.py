"""Size-limit policy for submissions.

A port of the legacy ``arXiv/Submit/Size_limits.pm``. It keeps *policy*
(the limit values) separate from *enforcement* (the size check), so the
numbers can be tuned without touching the checking logic.

There are three independent limits, each a mapping keyed by archive with a
``'default'`` fallback.

* ``max_uncompressed_total`` -- sum of all extracted files
* ``max_uncompressed_per_file`` -- any single extracted file
* ``max_compressed`` -- size of the compressed upload

All limits default to 50 MB, the legacy arXiv size guideline.

Only the total and per-file uncompressed limits are *enforced* by
:func:`check_sizes`; ``max_compressed`` is defined for completeness and future
tuning but is not currently checked.

Values are handled in **bytes** internally.

This module is pure domain code and must not depend on Flask.
"""

from dataclasses import dataclass
from typing import List, Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict

from arxiv.taxonomy.definitions import CATEGORIES

ONE_MB = 1024 * 1024

DEFAULT_MAX_SIZE_BYTES = 50 * ONE_MB

DEFAULT_ARCHIVE = "default"
"""Fallback key used when a category has no archive-specific override."""


def archive_for_category(category: Optional[str]) -> str:
    """Return the archive key for a category, or ``'default'`` if unknown."""
    if category and category in CATEGORIES:
        return CATEGORIES[category].in_archive
    return DEFAULT_ARCHIVE


@dataclass(frozen=True)
class SizeLimits:
    """The three size limits, each keyed by archive (values in bytes).

    Each mapping must contain a ``'default'`` entry. Per-archive overrides are
    optional; lookups fall back to ``'default'``.
    """

    max_uncompressed_total: Mapping[str, int]
    max_uncompressed_per_file: Mapping[str, int]
    max_compressed: Mapping[str, int]

    @staticmethod
    def _lookup(table: Mapping[str, int], category: Optional[str]) -> int:
        return table.get(archive_for_category(category), table[DEFAULT_ARCHIVE])

    def total_limit(self, category: Optional[str] = None) -> int:
        return self._lookup(self.max_uncompressed_total, category)

    def per_file_limit(self, category: Optional[str] = None) -> int:
        return self._lookup(self.max_uncompressed_per_file, category)

    def compressed_limit(self, category: Optional[str] = None) -> int:
        return self._lookup(self.max_compressed, category)


def _mb(num_bytes: int) -> str:
    return f"{num_bytes / ONE_MB:.1f} MB"


class OversizeReason(BaseModel):
    """One reason a submission is oversize.

    The human-readable text is built on demand by :meth:`message` from the
    structured fields, so it is never stored or serialized."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["TOTAL", "PER_FILE"]
    """Which limit was exceeded."""

    limit_bytes: int
    """The limit that was exceeded, in bytes."""

    actual_bytes: int
    """The measured size, in bytes."""

    path: Optional[str] = None
    """The offending file, for ``'PER_FILE'`` reasons."""

    def message(self) -> str:
        """Build the human-readable description from this reason's data."""
        if self.kind == "PER_FILE":
            return (f"File '{self.path}' is {_mb(self.actual_bytes)}, exceeding "
                    f"the {_mb(self.limit_bytes)} per-file limit.")
        return (f"Total uncompressed size {_mb(self.actual_bytes)} "
                f"exceeds the {_mb(self.limit_bytes)} limit.")


def check_sizes(total_uncompressed: int,
                per_file_sizes: Optional[Mapping[str, int]] = None,
                primary_category: Optional[str] = None,
                *,
                limits: SizeLimits) -> List[OversizeReason]:
    """Return the reasons a submission is oversize, or ``[]`` if within limits.

    Enforces the total-uncompressed and per-file-uncompressed limits, matching
    the legacy ``check_sizes``.

    Parameters
    ----------
    total_uncompressed
        Sum of all extracted files, in bytes.
    per_file_sizes
        Mapping of file path to size in bytes. Empty/omitted skips the
        per-file check.
    primary_category
        Primary classification category, used to select per-archive limits.
    limits
        Limits to enforce. Required and keyword-only, so callers must pass the
        authoritative limits (e.g. ``SubmitApi.get_size_limits()``) rather than
        silently falling back to a default. Pass ``SIZE_LIMIT_POLICY`` for the
        built-in 50 MB policy.
    """
    per_file_sizes = per_file_sizes or {}
    reasons: List[OversizeReason] = []

    total_limit = limits.total_limit(primary_category)
    if total_uncompressed > total_limit:
        reasons.append(OversizeReason(
            kind="TOTAL",
            limit_bytes=total_limit,
            actual_bytes=total_uncompressed,
        ))

    per_file_limit = limits.per_file_limit(primary_category)
    for path, size in per_file_sizes.items():
        if size > per_file_limit:
            reasons.append(OversizeReason(
                kind="PER_FILE",
                limit_bytes=per_file_limit,
                actual_bytes=size,
                path=path,
            ))
    return reasons


SIZE_LIMIT_POLICY = SizeLimits(
    max_uncompressed_total={"default": 50 * ONE_MB},
    max_uncompressed_per_file={"default": 50 * ONE_MB},
    max_compressed={"default": 50 * ONE_MB},
)
"""This is the current in effect size limit policy for the app."""
