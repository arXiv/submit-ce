"""Integration tests for GsFileStore against real GCS (arxiv-submit-dev / arxiv-development).

Requires Google Cloud credentials with access to the arxiv-development project.
Run with: TEST_GS_FILE_STORE_AT_GCP=1 uv run pytest submit_ce/implementations/file_store/tests/test_gs_file_store.py -v
"""
import json
import os
import tarfile
import uuid
from io import BytesIO

import pytest
from google.cloud import storage

from arxiv.files import FileDoesNotExist
from submit_ce.implementations.file_store.gs_file_store import GsFileStore

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_GS_FILE_STORE_AT_GCP"),
    reason="Set TEST_GS_FILE_STORE_AT_GCP=1 and set application default "\
    "credentials to run GCS integration tests",
)

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
    # Reuse the same dev bucket + test prefix for QA so the fixture's
    # prefix-based cleanup also removes any QA metadata written here.
    return GsFileStore(gs_bucket=bucket_name, gs_prefix=gs_prefix,
                       qa_bucket=bucket_name, qa_prefix=gs_prefix,
                       client=gcs_client)


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


def test_get_qa_artifact_info(store, sub_id):
    # Only the preview and source package exist for this submission.
    store.store_preview(sub_id, BytesIO(b"%PDF-1.4 fake"))
    tar_stream = make_targz({"main.tex": b"hello"})
    f = FakeFile("pkg.tar.gz", b"", "application/gzip")
    f.stream = tar_stream
    store.store_source_package(sub_id, f, chunk_size=4096)

    urls, crc32c = store.get_qa_artifact_info(sub_id)

    assert set(urls) == {"pdf", "source"}
    assert set(crc32c) == {"pdf", "source"}
    # URL points at the right object and carries a numeric generation suffix.
    base, sep, gen = urls["pdf"].partition("#")
    assert base.startswith(f"gs://{BUCKET_NAME}/")
    assert base.endswith(f"{sub_id}.pdf")
    assert sep == "#" and gen.isdigit()
    assert crc32c["pdf"]  # non-empty crc32c


def test_store_qa_metadata(store, sub_id):
    content = {
        "name": "arXiv Submission Snapshot Metadata",
        "version": "1.1",
        "arXiv_submissions": {"submission_id": sub_id, "type": "new"},
    }
    store.store_qa_metadata(sub_id, content)

    path = store._qa_meta_json_path(sub_id)
    assert path.endswith(f"{sub_id}/{sub_id}.meta.json")
    blob = store.qa_bucket.blob(path)
    assert blob.exists()
    assert json.loads(blob.download_as_bytes()) == content


# ---------------------------------------------------------------------------
# Artifact tests: directives, compile_log, compile_json, preflight,
#                 request_log, source_log
# ---------------------------------------------------------------------------

ARTIFACTS = [
    ("directives",   b'{"compiler": "pdflatex"}'),
    ("compile_log",  b"Compilation log content"),
    ("compile_json", b'{"status": "success"}'),
    ("preflight",    b'{"issues": []}'),
    ("request_log",  b"Request log content"),
    ("source_log",   b"Source log content"),
]


@pytest.fixture
def upload_artifact(store):
    """Upload arbitrary bytes to the correct GCS path for a given resource."""
    def _upload(sub_id: str, resource: str, content: bytes) -> None:
        path = getattr(store, f'_{resource}_path')(sub_id)
        blob = store.bucket.blob(str(path))
        blob.upload_from_file(BytesIO(content))
    return _upload


@pytest.mark.parametrize("resource,content", ARTIFACTS)
def test_artifact_missing_returns_FileDoesNotExist(store, sub_id, resource, content):
    result = getattr(store, f'get_{resource}')(sub_id)
    assert isinstance(result, FileDoesNotExist)


@pytest.mark.parametrize("resource,content", ARTIFACTS)
def test_artifact_does_not_exist_initially(store, sub_id, resource, content):
    assert not getattr(store, f'does_{resource}_exist')(sub_id)


@pytest.mark.parametrize("resource,content", ARTIFACTS)
def test_artifact_does_exist_after_upload(store, sub_id, upload_artifact, resource, content):
    upload_artifact(sub_id, resource, content)
    assert getattr(store, f'does_{resource}_exist')(sub_id)


@pytest.mark.parametrize("resource,content", ARTIFACTS)
def test_artifact_get_returns_correct_content(store, sub_id, upload_artifact, resource, content):
    upload_artifact(sub_id, resource, content)
    blob = getattr(store, f'get_{resource}')(sub_id)
    assert blob.download_as_bytes() == content


@pytest.mark.parametrize("resource,content", ARTIFACTS)
def test_artifact_checksum_is_nonempty(store, sub_id, upload_artifact, resource, content):
    upload_artifact(sub_id, resource, content)
    checksum = getattr(store, f'get_{resource}_checksum')(sub_id)
    assert checksum


@pytest.mark.parametrize("resource,content", ARTIFACTS)
def test_artifact_delete(store, sub_id, upload_artifact, resource, content):
    upload_artifact(sub_id, resource, content)
    getattr(store, f'delete_{resource}')(sub_id)
    assert not getattr(store, f'does_{resource}_exist')(sub_id)
