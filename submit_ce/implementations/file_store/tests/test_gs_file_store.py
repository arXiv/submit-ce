"""Integration tests for GsFileStore against real GCS (arxiv-submit-dev / arxiv-development).

Requires Google Cloud credentials with access to the arxiv-development project.
Run with: uv run pytest submit_ce/implementations/file_store/tests/test_gs_file_store.py -v
"""
import tarfile
import uuid
from io import BytesIO

import pytest
from google.cloud import storage

from arxiv.files import FileDoesNotExist
from submit_ce.implementations.file_store.gs_file_store import GsFileStore

BUCKET_NAME = "arxiv-submit-dev"
PROJECT = "arxiv-development"
TEST_PREFIX_BASE = "test_gs_file_store"


@pytest.fixture(scope="session")
def gcs_client():
    return storage.Client(project=PROJECT)


@pytest.fixture(scope="session")
def bucket(gcs_client):
    b = gcs_client.bucket(BUCKET_NAME)
    if gcs_client.project != PROJECT:
        pytest.fail(f"GCS client project is {gcs_client.project!r}, expected {PROJECT!r}; refusing to run against non-dev bucket.")
    if "dev" not in BUCKET_NAME:
        pytest.fail(f"Bucket name {BUCKET_NAME!r} does not contain 'dev'; refusing to run against non-dev bucket.")
    chosen = None
    for _ in range(8):
        candidate = f"{TEST_PREFIX_BASE}/{uuid.uuid4().hex[:12]}"
        existing = list(gcs_client.list_blobs(b, prefix=candidate, max_results=1))
        if not existing:
            chosen = candidate
            break
    if chosen is None:
        pytest.fail(
            f"Could not find a free prefix under {TEST_PREFIX_BASE!r} in {BUCKET_NAME} "
            "after 8 attempts; aborting to avoid interference with existing data."
        )
    yield BUCKET_NAME, chosen
    blobs = list(gcs_client.list_blobs(b, prefix=chosen))
    if blobs:
        b.delete_blobs(blobs)


@pytest.fixture
def store(gcs_client, bucket):
    bucket_name, gs_prefix = bucket
    return GsFileStore(gs_bucket=bucket_name, gs_prefix=gs_prefix, client=gcs_client)


@pytest.fixture
def sub_id():
    """Unique submission ID per test to avoid cross-test interference."""
    return uuid.uuid4().hex[:8]


class FakeFile:
    """Minimal SubmitFile stand-in."""
    def __init__(self, filename: str, content: bytes, content_type: str = "text/plain"):
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_store_and_get_source_file(store, sub_id):
    content = b"\\documentclass{article}"
    status = store.store_source_file(sub_id, FakeFile("main.tex", content), chunk_size=4096)

    assert status.name == "main.tex"
    assert status.bytes == len(content)

    blob = store.get_source_file(sub_id, "main.tex")
    assert blob.download_as_bytes() == content


def test_get_source_file_missing_returns_FileDoesNotExist(store, sub_id):
    result = store.get_source_file(sub_id, "nope.tex")
    assert isinstance(result, FileDoesNotExist)


def test_get_source_file_info(store, sub_id):
    content = b"hello world"
    store.store_source_file(sub_id, FakeFile("readme.txt", content), chunk_size=4096)

    info = store.get_source_file_info(sub_id, "readme.txt")
    assert info.name == "readme.txt"
    assert info.bytes == len(content)


def test_get_source_file_info_missing_raises(store, sub_id):
    with pytest.raises(FileNotFoundError):
        store.get_source_file_info(sub_id, "ghost.tex")


def test_delete_source_file(store, sub_id):
    store.store_source_file(sub_id, FakeFile("bye.tex", b"gone"), chunk_size=4096)
    store.delete_source_file(sub_id, "bye.tex")
    assert isinstance(store.get_source_file(sub_id, "bye.tex"), FileDoesNotExist)


def test_get_workspace_lists_files(store, sub_id):
    store.store_source_file(sub_id, FakeFile("a.tex", b"aaa"), chunk_size=4096)
    store.store_source_file(sub_id, FakeFile("b.tex", b"bbb"), chunk_size=4096)

    ws = store.get_workspace(sub_id)
    names = {f.name for f in ws.files}
    assert {"a.tex", "b.tex"} <= names
    assert ws.size > 0


def test_store_source_package_extracts_members(store, sub_id):
    tar_stream = make_targz({"main.tex": b"hello", "fig.pdf": b"figdata"})
    f = FakeFile("pkg.tar.gz", b"", "application/gzip")
    f.stream = tar_stream
    result = store.store_source_package(sub_id, f, chunk_size=4096)

    stored_names = {item["file"] for item in result}
    assert "main.tex" in stored_names
    assert "fig.pdf" in stored_names


def test_store_and_get_preview(store, sub_id):
    pdf = b"%PDF-1.4 fake"
    checksum = store.store_preview(sub_id, BytesIO(pdf))

    assert checksum  # non-empty crc32c
    blob = store.get_preview(sub_id)
    assert blob.download_as_bytes() == pdf


def test_get_preview_missing_returns_FileDoesNotExist(store, sub_id):
    result = store.get_preview(sub_id)
    assert isinstance(result, FileDoesNotExist)


def test_does_preview_exist(store, sub_id):
    assert not store.does_preview_exist(sub_id)
    store.store_preview(sub_id, BytesIO(b"%PDF"))
    assert store.does_preview_exist(sub_id)


def test_delete_preview(store, sub_id):
    store.store_preview(sub_id, BytesIO(b"%PDF"))
    store.delete_preview(sub_id)
    assert not store.does_preview_exist(sub_id)


def test_delete_all_source_files(store, sub_id):
    store.store_source_file(sub_id, FakeFile("x.tex", b"x"), chunk_size=4096)
    store.store_source_file(sub_id, FakeFile("y.tex", b"y"), chunk_size=4096)
    store.delete_all_source_files(sub_id)

    ws = store.get_workspace(sub_id)
    assert ws.files == []


def test_delete_workspace(store, sub_id):
    store.store_source_file(sub_id, FakeFile("keep.tex", b"data"), chunk_size=4096)
    store.delete_workspace(sub_id)

    ws = store.get_workspace(sub_id)
    assert ws.files == []


def test_is_available(store):
    assert store.is_available() is True
