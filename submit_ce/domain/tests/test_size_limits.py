"""Tests for the size-limit policy module (:mod:`submit_ce.domain.size_limits`)."""

from submit_ce.domain.size_limits import (
    ONE_MB,
    DEFAULT_MAX_SIZE_BYTES,
    SizeLimits,
    SIZE_LIMIT_POLICY,
    archive_for_category,
    check_sizes,
)

MB = ONE_MB


# --- limit values & lookups -------------------------------------------------

def test_default_limit_is_50mb():
    assert DEFAULT_MAX_SIZE_BYTES == 50 * ONE_MB


def test_defaults_populate_all_three_limits():
    limits = SIZE_LIMIT_POLICY
    assert limits.total_limit() == DEFAULT_MAX_SIZE_BYTES
    assert limits.per_file_limit() == DEFAULT_MAX_SIZE_BYTES
    assert limits.compressed_limit() == DEFAULT_MAX_SIZE_BYTES


def test_constructor_sets_each_limit_independently():
    limits = SizeLimits(
        max_uncompressed_total={"default": 10 * MB},
        max_uncompressed_per_file={"default": 20 * MB},
        max_compressed={"default": 30 * MB},
    )
    assert limits.total_limit() == 10 * MB
    assert limits.per_file_limit() == 20 * MB
    assert limits.compressed_limit() == 30 * MB


def test_archive_for_category():
    assert archive_for_category("math.GT") == "math"
    assert archive_for_category("astro-ph.GA") == "astro-ph"
    assert archive_for_category("hep-th") == "hep-th"
    assert archive_for_category(None) == "default"
    assert archive_for_category("not.a.category") == "default"


def test_per_archive_override_falls_back_to_default():
    limits = SizeLimits(
        max_uncompressed_total={"default": 100, "astro-ph": 999},
        max_uncompressed_per_file={"default": 100},
        max_compressed={"default": 100},
    )
    # astro-ph.GA resolves to the astro-ph override...
    assert limits.total_limit("astro-ph.GA") == 999
    # ...while other categories fall back to 'default'.
    assert limits.total_limit("math.GT") == 100
    assert limits.total_limit(None) == 100


# --- check_sizes ------------------------------------------------------------

def test_within_limits_returns_no_reasons():
    limits = SIZE_LIMIT_POLICY
    reasons = check_sizes(total_uncompressed=10 * MB,
                          per_file_sizes={"a.tex": 1 * MB, "b.png": 5 * MB},
                          limits=limits)
    assert reasons == []


def test_total_over_limit_flags_total():
    limits = SIZE_LIMIT_POLICY
    reasons = check_sizes(total_uncompressed=60 * MB, limits=limits)
    assert len(reasons) == 1
    assert reasons[0].kind == "TOTAL"
    assert reasons[0].actual_bytes == 60 * MB
    assert reasons[0].limit_bytes == DEFAULT_MAX_SIZE_BYTES


def test_per_file_over_limit_flags_each_file():
    limits = SIZE_LIMIT_POLICY
    reasons = check_sizes(
        total_uncompressed=10 * MB,  # total is fine
        per_file_sizes={"small.tex": 1 * MB, "huge.dat": 60 * MB},
        limits=limits,
    )
    assert len(reasons) == 1
    assert reasons[0].kind == "PER_FILE"
    assert reasons[0].path == "huge.dat"
    assert reasons[0].actual_bytes == 60 * MB


def test_both_dimensions_can_trip():
    limits = SIZE_LIMIT_POLICY
    reasons = check_sizes(
        total_uncompressed=120 * MB,
        per_file_sizes={"huge.dat": 60 * MB},
        limits=limits,
    )
    kinds = sorted(r.kind for r in reasons)
    assert kinds == ["PER_FILE", "TOTAL"]


def test_exactly_at_limit_is_not_oversize():
    limits = SIZE_LIMIT_POLICY
    assert check_sizes(DEFAULT_MAX_SIZE_BYTES,
                       {"f": DEFAULT_MAX_SIZE_BYTES},
                       limits=limits) == []


def test_compressed_limit_is_not_enforced():
    # A tiny compressed limit but generous total/per-file: check_sizes only
    # looks at total + per-file, never compressed.
    limits = SizeLimits(
        max_uncompressed_total={"default": 50 * MB},
        max_uncompressed_per_file={"default": 50 * MB},
        max_compressed={"default": 1},
    )
    assert check_sizes(10 * MB, {"a": 1 * MB}, limits=limits) == []


def test_per_archive_limit_used_in_check():
    limits = SizeLimits(
        max_uncompressed_total={"default": 100 * MB, "astro-ph": 5 * MB},
        max_uncompressed_per_file={"default": 100 * MB},
        max_compressed={"default": 100 * MB},
    )
    # 10MB is over the 5MB astro-ph limit but under the 100MB default.
    assert check_sizes(10 * MB, primary_category="astro-ph.GA", limits=limits)
    assert check_sizes(10 * MB, primary_category="math.GT", limits=limits) == []
