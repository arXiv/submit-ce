"""Tests for the size-limit policy module (:mod:`submit_ce.domain.size_limits`)."""

from submit_ce.domain import size_limits as sl
from submit_ce.domain.size_limits import (
    ONE_KB,
    DEFAULT_MAX_SIZE_KB,
    DEFAULT_MAX_SIZE_BYTES,
    SizeLimits,
    archive_for_category,
    check_sizes,
    is_oversize,
    summarize,
)

MB = ONE_KB * ONE_KB


# --- limit values & lookups -------------------------------------------------

def test_default_limit_is_50mb():
    assert DEFAULT_MAX_SIZE_KB == 50_000
    assert DEFAULT_MAX_SIZE_BYTES == 50_000 * ONE_KB


def test_defaults_populate_all_three_limits():
    limits = SizeLimits.defaults()
    assert limits.total_limit() == DEFAULT_MAX_SIZE_BYTES
    assert limits.per_file_limit() == DEFAULT_MAX_SIZE_BYTES
    assert limits.compressed_limit() == DEFAULT_MAX_SIZE_BYTES


def test_from_kb_converts_to_bytes_independently():
    limits = SizeLimits.from_kb(total_kb=10, per_file_kb=20, compressed_kb=30)
    assert limits.total_limit() == 10 * ONE_KB
    assert limits.per_file_limit() == 20 * ONE_KB
    assert limits.compressed_limit() == 30 * ONE_KB


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
    limits = SizeLimits.from_kb(50_000, 50_000, 50_000)
    reasons = check_sizes(total_uncompressed=10 * MB,
                          per_file_sizes={"a.tex": 1 * MB, "b.png": 5 * MB},
                          limits=limits)
    assert reasons == []
    assert is_oversize(10 * MB, {"a.tex": 1 * MB}, limits=limits) is False


def test_total_over_limit_flags_total():
    limits = SizeLimits.from_kb(50_000, 50_000, 50_000)
    reasons = check_sizes(total_uncompressed=60 * MB, limits=limits)
    assert len(reasons) == 1
    assert reasons[0].kind == "total"
    assert reasons[0].actual == 60 * MB
    assert reasons[0].limit == DEFAULT_MAX_SIZE_BYTES
    assert is_oversize(60 * MB, limits=limits) is True


def test_per_file_over_limit_flags_each_file():
    limits = SizeLimits.from_kb(50_000, 50_000, 50_000)
    reasons = check_sizes(
        total_uncompressed=10 * MB,  # total is fine
        per_file_sizes={"small.tex": 1 * MB, "huge.dat": 60 * MB},
        limits=limits,
    )
    assert len(reasons) == 1
    assert reasons[0].kind == "per_file"
    assert reasons[0].path == "huge.dat"
    assert reasons[0].actual == 60 * MB


def test_both_dimensions_can_trip():
    limits = SizeLimits.from_kb(50_000, 50_000, 50_000)
    reasons = check_sizes(
        total_uncompressed=120 * MB,
        per_file_sizes={"huge.dat": 60 * MB},
        limits=limits,
    )
    kinds = sorted(r.kind for r in reasons)
    assert kinds == ["per_file", "total"]


def test_exactly_at_limit_is_not_oversize():
    limits = SizeLimits.from_kb(50_000, 50_000, 50_000)
    assert check_sizes(DEFAULT_MAX_SIZE_BYTES,
                       {"f": DEFAULT_MAX_SIZE_BYTES},
                       limits=limits) == []


def test_compressed_limit_is_not_enforced():
    # A tiny per-file/total but a defined compressed limit: check_sizes only
    # looks at total + per-file, never compressed.
    limits = SizeLimits.from_kb(50_000, 50_000, compressed_kb=1)
    assert check_sizes(10 * MB, {"a": 1 * MB}, limits=limits) == []


def test_per_archive_limit_used_in_check():
    limits = SizeLimits(
        max_uncompressed_total={"default": 100 * MB, "astro-ph": 5 * MB},
        max_uncompressed_per_file={"default": 100 * MB},
        max_compressed={"default": 100 * MB},
    )
    # 10MB is over the 5MB astro-ph limit but under the 100MB default.
    assert is_oversize(10 * MB, primary_category="astro-ph.GA", limits=limits)
    assert not is_oversize(10 * MB, primary_category="math.GT", limits=limits)


def test_summarize_joins_messages():
    limits = SizeLimits.from_kb(50_000, 50_000, 50_000)
    reasons = check_sizes(120 * MB, {"huge.dat": 60 * MB}, limits=limits)
    text = summarize(reasons)
    assert "Total uncompressed size" in text
    assert "huge.dat" in text


# --- environment escape hatches ---------------------------------------------

def test_override_env_doubles_limits(monkeypatch):
    monkeypatch.setenv(sl.OVERRIDE_ENV, "1")
    limits = SizeLimits.defaults()
    assert limits.total_limit() == 2 * DEFAULT_MAX_SIZE_BYTES


def test_override_env_falsey_does_nothing(monkeypatch):
    monkeypatch.setenv(sl.OVERRIDE_ENV, "0")
    assert SizeLimits.defaults().total_limit() == DEFAULT_MAX_SIZE_BYTES


def test_maxsize_env_raises_limits(monkeypatch):
    monkeypatch.setenv(sl.MAXSIZE_ENV, "200000")  # 200,000 KB
    assert SizeLimits.defaults().total_limit() == 200_000 * ONE_KB


def test_maxsize_env_only_raises_never_lowers(monkeypatch):
    monkeypatch.setenv(sl.MAXSIZE_ENV, "1")  # below the default
    assert SizeLimits.defaults().total_limit() == DEFAULT_MAX_SIZE_BYTES


def test_maxsize_env_ignores_garbage(monkeypatch):
    monkeypatch.setenv(sl.MAXSIZE_ENV, "not-a-number")
    assert SizeLimits.defaults().total_limit() == DEFAULT_MAX_SIZE_BYTES
