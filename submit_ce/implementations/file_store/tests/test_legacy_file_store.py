"""Tests for LegacyFileStore artifact methods (directives, logs, preflight, etc.)."""
import pytest
from pathlib import Path

from arxiv.files import FileDoesNotExist, LocalFileObj
from submit_ce.implementations.file_store.legacy_file_store import LegacyFileStore

SUB_ID = "12345678"

ARTIFACTS = [
    ("directives",   b'{"compiler": "pdflatex"}'),
    ("compile_log",  b"Compilation log content"),
    ("compile_json", b'{"status": "success"}'),
    ("preflight",    b'{"issues": []}'),
    ("request_log",  b"Request log content"),
    ("source_log",   b"Source log content"),
]


@pytest.fixture
def store(tmp_path):
    return LegacyFileStore(root_dir=tmp_path)


@pytest.fixture
def sub_dir(store):
    """Ensure the submission directory exists and return it."""
    path = store._submission_path(SUB_ID)
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture
def upload_artifact(store, sub_dir):
    """Write bytes to the correct path for a given resource."""
    def _upload(resource: str, content: bytes) -> None:
        path: Path = getattr(store, f'_{resource}_path')(SUB_ID)
        path.write_bytes(content)
    return _upload


# ---------------------------------------------------------------------------
# Artifact tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("resource,content", ARTIFACTS)
def test_artifact_missing_returns_FileDoesNotExist(store, sub_dir, resource, content):
    result = getattr(store, f'get_{resource}')(SUB_ID)
    assert isinstance(result, FileDoesNotExist)


@pytest.mark.parametrize("resource,content", ARTIFACTS)
def test_artifact_does_not_exist_initially(store, sub_dir, resource, content):
    assert not getattr(store, f'does_{resource}_exist')(SUB_ID)


@pytest.mark.parametrize("resource,content", ARTIFACTS)
def test_artifact_does_exist_after_upload(store, upload_artifact, resource, content):
    upload_artifact(resource, content)
    assert getattr(store, f'does_{resource}_exist')(SUB_ID)


@pytest.mark.parametrize("resource,content", ARTIFACTS)
def test_artifact_get_returns_correct_content(store, upload_artifact, resource, content):
    upload_artifact(resource, content)
    result = getattr(store, f'get_{resource}')(SUB_ID)
    assert isinstance(result, LocalFileObj)
    with result.open('rb') as fh:
        assert fh.read() == content


@pytest.mark.parametrize("resource,content", ARTIFACTS)
def test_artifact_checksum_is_nonempty(store, upload_artifact, resource, content):
    upload_artifact(resource, content)
    checksum = getattr(store, f'get_{resource}_checksum')(SUB_ID)
    assert checksum


@pytest.mark.parametrize("resource,content", ARTIFACTS)
def test_artifact_delete(store, upload_artifact, resource, content):
    upload_artifact(resource, content)
    getattr(store, f'delete_{resource}')(SUB_ID)
    assert not getattr(store, f'does_{resource}_exist')(SUB_ID)


@pytest.mark.parametrize("resource,content", ARTIFACTS)
def test_artifact_delete_missing_is_noop(store, sub_dir, resource, content):
    getattr(store, f'delete_{resource}')(SUB_ID)  # must not raise
    assert not getattr(store, f'does_{resource}_exist')(SUB_ID)
