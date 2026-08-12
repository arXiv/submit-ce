"""Unit tests for archive member-path safety (SUBMISSION-230).

These exercise the pure `safe_member_rel` helper and the in-memory
`MockFileStore`, so they run without GCS credentials as part of `./test.sh`.
The equivalent behavior against real GCS is covered (under the GCP-only skip)
in test_gs_file_store.py.
"""
import io
import tarfile
import zipfile
from io import BytesIO

import pytest

from submit_ce.implementations.file_store.file_store_mixin import safe_member_rel
from submit_ce.implementations.file_store.gs_file_store import GsFileStore
from submit_ce.implementations.file_store.mock_file_store import MockFileStore


class FakeFile:
    """Minimal SubmitFile stand-in."""
    def __init__(self, filename: str, content: bytes = b"", content_type: str = "application/gzip"):
        self.filename = filename
        self.content_type = content_type
        self.stream = BytesIO(content)


def make_targz(files: dict[str, bytes]) -> BytesIO:
    buf = BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, BytesIO(data))
    buf.seek(0)
    return buf


def make_zip(files: dict[str, bytes]) -> BytesIO:
    buf = BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    buf.seek(0)
    return buf


# ---- safe_member_rel: pure helper -----------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("main.tex", "main.tex"),
    ("./main.tex", "main.tex"),          # strip "./" (SUBMISSION-224)
    ("fig/plot.png", "fig/plot.png"),
    ("./fig/../fig/plot.png", "fig/plot.png"),  # collapses interior "."/".."
    ("a/b/c.tex", "a/b/c.tex"),
])
def test_safe_member_rel_accepts_and_normalizes(raw, expected):
    assert safe_member_rel(raw) == expected


@pytest.mark.parametrize("raw", [".", "", "./"])
def test_safe_member_rel_returns_none_for_root(raw):
    assert safe_member_rel(raw) is None


@pytest.mark.parametrize("raw", [
    "../evil.tex",
    "../../etc/passwd",
    "a/../../evil.tex",       # normalizes to "../evil.tex"
    "..",
    "/etc/passwd",            # absolute
    "/tmp/x",
])
def test_safe_member_rel_rejects_unsafe(raw):
    with pytest.raises(ValueError):
        safe_member_rel(raw)


# ---- MockFileStore.store_source_package: end-to-end ------------------------

def test_mock_store_extracts_clean_nested_paths():
    store = MockFileStore()
    f = FakeFile("pkg.tar.gz")
    f.stream = make_targz({"./main.tex": b"hello", "./fig/plot.png": b"png"})
    result = store.store_source_package("sub1", f, chunk_size=4096)

    paths = {item.path for item in result}
    assert "main.tex" in paths
    assert "fig/plot.png" in paths
    assert not any(p.startswith("./") for p in paths)


def test_mock_store_rejects_traversal_tar():
    store = MockFileStore()
    f = FakeFile("pkg.tar.gz")
    f.stream = make_targz({"main.tex": b"ok", "../../evil.tex": b"pwn"})
    with pytest.raises(ValueError):
        store.store_source_package("sub2", f, chunk_size=4096)


def test_mock_store_rejects_traversal_zip():
    store = MockFileStore()
    f = FakeFile("pkg.zip", content_type="application/zip")
    f.stream = make_zip({"main.tex": b"ok", "../evil.tex": b"pwn"})
    with pytest.raises(ValueError):
        store.store_source_package("sub3", f, chunk_size=4096)


def test_mock_store_rejects_absolute_member():
    store = MockFileStore()
    f = FakeFile("pkg.tar.gz")
    f.stream = make_targz({"/etc/passwd": b"pwn"})
    with pytest.raises(ValueError):
        store.store_source_package("sub4", f, chunk_size=4096)


# ---- GsFileStore._check_path_safe: real containment ------------------------

def _bare_gs_store(gs_prefix="submissions", source_prefix="src"):
    """A GsFileStore with just enough attributes to exercise path logic,
    without constructing a GCS client."""
    store = object.__new__(GsFileStore)
    store.gs_prefix = gs_prefix
    store.source_prefix = source_prefix
    return store


def test_check_path_safe_accepts_paths_within_source():
    store = _bare_gs_store()
    root = store._source_path("123")
    store._check_path_safe("123", f"{root}/main.tex")
    store._check_path_safe("123", f"{root}/fig/plot.png")


def test_check_path_safe_rejects_traversal_that_prefix_matches():
    """A key like ".../src/../../evil" literally starts with ".../src" but
    escapes the submission once ".." is resolved; the hardened check catches
    it where a bare startswith would not (SUBMISSION-230)."""
    store = _bare_gs_store()
    root = store._source_path("123")
    with pytest.raises(RuntimeError):
        store._check_path_safe("123", f"{root}/../../evil")


def test_check_path_safe_rejects_sibling_prefix():
    """".../src-other/x" must not pass just because it starts with ".../src"."""
    store = _bare_gs_store()
    root = store._source_path("123")
    with pytest.raises(RuntimeError):
        store._check_path_safe("123", f"{root}-other/x")
