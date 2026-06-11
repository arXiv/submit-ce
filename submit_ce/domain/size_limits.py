"""Size-limit policy for submissions.

A port of the legacy ``arXiv/Submit/Size_limits.pm``. It keeps *policy*
(the limit values) separate from *enforcement* (the size check), so the
numbers can be tuned without touching the checking logic.

There are three independent limits, each a mapping keyed by archive with a
``'default'`` fallback (matching legacy, where only ``'default'`` is
populated but per-archive overrides are supported):

* ``max_uncompressed_total`` -- sum of all extracted files
* ``max_uncompressed_per_file`` -- any single extracted file
* ``max_compressed`` -- size of the compressed upload

All limits default to 50,000 KB (50 MB), the legacy arXiv size guideline.

Only the total and per-file uncompressed limits are *enforced* by
:func:`check_sizes` (matching legacy ``check_sizes``); ``max_compressed`` is
defined for completeness and future tuning but is not currently checked.

Values are handled in **bytes** internally (matching
:attr:`submit_ce.domain.submission.Submission.uncompressed_size` and
:attr:`submit_ce.domain.uploads.FileStatus.bytes`); the documented defaults
are expressed in KB to mirror the legacy module.

This module is pure domain code and must not depend on Flask. The two
environment escape hatches below mirror the legacy ``OVERRIDE``/``MAXSIZE``
knobs and are read at call time so tests can raise the limits without
reconfiguring the app.
"""

import os
from dataclasses import dataclass
from typing import List, Mapping, Optional

from arxiv.taxonomy.definitions import CATEGORIES

ONE_KB = 1024
DEFAULT_MAX_SIZE_KB = 50_000
"""Legacy arXiv size guideline: 50,000 KB (50 MB)."""

DEFAULT_MAX_SIZE_BYTES = DEFAULT_MAX_SIZE_KB * ONE_KB

DEFAULT_ARCHIVE = "default"
"""Fallback key used when a category has no archive-specific override."""

OVERRIDE_ENV = "SUBMIT_OVERSIZE_OVERRIDE"
"""When truthy, doubles every limit (port of legacy ``OVERRIDE``)."""

MAXSIZE_ENV = "SUBMIT_OVERSIZE_MAXSIZE_KB"
"""When set to a number of KB, raises every limit to at least that value
(port of legacy ``MAXSIZE``)."""


def _truthy(value: Optional[str]) -> bool:
    return bool(value) and value.strip().lower() not in ("0", "false", "no", "")


def _apply_env_escapes(base_bytes: int) -> int:
    """Apply the ``MAXSIZE``/``OVERRIDE`` escape hatches to a limit."""
    maxsize = os.environ.get(MAXSIZE_ENV)
    if maxsize:
        try:
            base_bytes = max(base_bytes, int(maxsize) * ONE_KB)
        except ValueError:
            pass
    if _truthy(os.environ.get(OVERRIDE_ENV)):
        base_bytes *= 2
    return base_bytes


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

    @classmethod
    def defaults(cls) -> "SizeLimits":
        """Limits at the legacy default (50 MB), with env escapes applied."""
        return cls.from_kb(DEFAULT_MAX_SIZE_KB,
                           DEFAULT_MAX_SIZE_KB,
                           DEFAULT_MAX_SIZE_KB)

    @classmethod
    def from_kb(cls, total_kb: int, per_file_kb: int,
                compressed_kb: int) -> "SizeLimits":
        """Build limits from KB values (e.g. from config), applying escapes."""
        return cls(
            max_uncompressed_total={
                DEFAULT_ARCHIVE: _apply_env_escapes(total_kb * ONE_KB)},
            max_uncompressed_per_file={
                DEFAULT_ARCHIVE: _apply_env_escapes(per_file_kb * ONE_KB)},
            max_compressed={
                DEFAULT_ARCHIVE: _apply_env_escapes(compressed_kb * ONE_KB)},
        )

    @staticmethod
    def _lookup(table: Mapping[str, int], category: Optional[str]) -> int:
        return table.get(archive_for_category(category), table[DEFAULT_ARCHIVE])

    def total_limit(self, category: Optional[str] = None) -> int:
        return self._lookup(self.max_uncompressed_total, category)

    def per_file_limit(self, category: Optional[str] = None) -> int:
        return self._lookup(self.max_uncompressed_per_file, category)

    def compressed_limit(self, category: Optional[str] = None) -> int:
        return self._lookup(self.max_compressed, category)


@dataclass(frozen=True)
class OversizeReason:
    """One reason a submission is oversize, with human-readable text."""

    kind: str
    """``'total'`` or ``'per_file'``."""

    message: str
    limit: int
    """The limit that was exceeded, in bytes."""

    actual: int
    """The measured size, in bytes."""

    path: Optional[str] = None
    """The offending file, for ``'per_file'`` reasons."""


def _mb(num_bytes: int) -> str:
    return f"{num_bytes / (ONE_KB * ONE_KB):.1f} MB"


def check_sizes(total_uncompressed: int,
                per_file_sizes: Optional[Mapping[str, int]] = None,
                primary_category: Optional[str] = None,
                limits: Optional[SizeLimits] = None) -> List[OversizeReason]:
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
        Limits to enforce. Defaults to :meth:`SizeLimits.defaults`.
    """
    limits = limits or SizeLimits.defaults()
    per_file_sizes = per_file_sizes or {}
    reasons: List[OversizeReason] = []

    total_limit = limits.total_limit(primary_category)
    if total_uncompressed > total_limit:
        reasons.append(OversizeReason(
            kind="total",
            message=(f"Total uncompressed size {_mb(total_uncompressed)} "
                     f"exceeds the {_mb(total_limit)} limit."),
            limit=total_limit,
            actual=total_uncompressed,
        ))

    per_file_limit = limits.per_file_limit(primary_category)
    for path, size in per_file_sizes.items():
        if size > per_file_limit:
            reasons.append(OversizeReason(
                kind="per_file",
                message=(f"File '{path}' is {_mb(size)}, exceeding the "
                         f"{_mb(per_file_limit)} per-file limit."),
                limit=per_file_limit,
                actual=size,
                path=path,
            ))
    return reasons


def is_oversize(total_uncompressed: int,
                per_file_sizes: Optional[Mapping[str, int]] = None,
                primary_category: Optional[str] = None,
                limits: Optional[SizeLimits] = None) -> bool:
    """Return ``True`` if the submission exceeds any enforced limit."""
    return bool(check_sizes(total_uncompressed, per_file_sizes,
                            primary_category, limits))


def summarize(reasons: List[OversizeReason]) -> str:
    """Join reason messages into a single human-readable warning string."""
    return " ".join(reason.message for reason in reasons)
