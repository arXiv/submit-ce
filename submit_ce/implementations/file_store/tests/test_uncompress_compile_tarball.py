"""Regression tests for ``GsFileStore.uncompress_compile_tarball`` parsing.

SUBMISSION-204: the log file in a tex2pdf ``outcome-src.json`` is named after
the main TeX file (e.g. ``paper.log``), not always ``main.log``. The parser used
to hardcode ``outcome["out_files"]["main.log"]``, which raised
``KeyError: 'main.log'`` for any submission whose top-level file wasn't
``main.tex``. These tests pin the fix: the log is located by matching the PDF's
stem (falling back to any ``.log``), and a missing log no longer crashes.

Pure unit tests -- the bucket/client are mocked, so no GCS credentials are
required (unlike the integration tests in ``test_gs_file_store.py``).
"""
import io
import json
import tarfile
from unittest.mock import MagicMock

from submit_ce.implementations.file_store.gs_file_store import GsFileStore


def _make_store() -> GsFileStore:
    """A GsFileStore backed by a mock client so __init__ never touches GCS."""
    return GsFileStore(gs_bucket="test-bucket", gs_prefix="p", client=MagicMock())


def _make_outcome_targz(outcome: dict, files: dict[str, bytes]) -> bytes:
    """Build a gzipped outcome tarball with an ``outcome-src.json`` member."""
    members = {"outcome-src.json": json.dumps(outcome).encode()}
    members.update(files)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _wire(store: GsFileStore, tar_bytes: bytes) -> None:
    """Point the outcome blob at tar_bytes and stub the store_* side effects."""
    outcome_blob = MagicMock()
    outcome_blob.download_as_bytes.return_value = tar_bytes
    store.bucket.blob.return_value = outcome_blob
    store.store_compile_log = MagicMock()
    store.store_preview = MagicMock()


def test_log_named_after_main_tex_file_is_found():
    """The exact SUBMISSION-204 case: log named like the PDF, not 'main.log'."""
    store = _make_store()
    outcome = {
        "pdf_file": "Hell_vs_FisRao_20251002.pdf",
        "status": "success",
        "out_files": {
            "Hell_vs_FisRao_20251002.pdf": {"name": "Hell_vs_FisRao_20251002.pdf"},
            "Hell_vs_FisRao_20251002.log": {"name": "Hell_vs_FisRao_20251002.log"},
        },
    }
    tar = _make_outcome_targz(outcome, {
        "Hell_vs_FisRao_20251002.pdf": b"%PDF-1.4 fake",
        "Hell_vs_FisRao_20251002.log": b"log body",
    })
    _wire(store, tar)

    store.uncompress_compile_tarball("1")  # must not raise KeyError

    store.store_compile_log.assert_called_once()
    store.store_preview.assert_called_once()
    assert store.store_compile_log.call_args.args[0] == "1"
    assert store.store_preview.call_args.args[0] == "1"


def test_main_log_still_found_for_main_tex_submissions():
    """Backward compatibility: a genuine 'main.log' is still located."""
    store = _make_store()
    outcome = {
        "pdf_file": "main.pdf",
        "status": "success",
        "out_files": {
            "main.pdf": {"name": "main.pdf"},
            "main.log": {"name": "main.log"},
        },
    }
    tar = _make_outcome_targz(outcome, {
        "main.pdf": b"%PDF-1.4 fake",
        "main.log": b"main log body",
    })
    _wire(store, tar)

    store.uncompress_compile_tarball("2")

    store.store_compile_log.assert_called_once()
    store.store_preview.assert_called_once()


def test_missing_log_does_not_raise_and_still_stores_preview():
    """A compile that produced no .log must not crash; the PDF still installs."""
    store = _make_store()
    outcome = {
        "pdf_file": "paper.pdf",
        "status": "success",
        "out_files": {"paper.pdf": {"name": "paper.pdf"}},
    }
    tar = _make_outcome_targz(outcome, {"paper.pdf": b"%PDF-1.4 fake"})
    _wire(store, tar)

    store.uncompress_compile_tarball("3")  # must not raise

    store.store_compile_log.assert_not_called()
    store.store_preview.assert_called_once()
