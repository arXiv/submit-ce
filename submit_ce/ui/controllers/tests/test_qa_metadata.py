"""Unit tests for the QA submission-snapshot controller (v1.2 schema).

Mocks ``current_app.api`` (a fake session + file store) so no DB or GCS is
needed. Verifies the 1.2 additions: ``metadata_checksum`` and per-file
``crc32c`` (and that the urls/crc32c only cover files that exist).
"""
import json
from unittest.mock import MagicMock

from arxiv.db.models import (
    Submission,
    SubmissionCategory,
    SubmissionAbsClassifierDatum,
    SubmissionClassifierDatum,
)
from arxiv.metadata.checksum import checksum_metadata

from submit_ce.domain.qa_metadata import ARXIV_SUBMISSIONS_FIELDS
from submit_ce.ui.controllers import qa_metadata as ctrl

SID = "4848983"


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _FakeSession:
    """Returns canned rows per queried model; usable as a context manager."""
    def __init__(self, by_model):
        self._by_model = by_model

    def query(self, model):
        return _FakeQuery(self._by_model.get(model, []))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_store():
    """File store stub: pdf + source exist (url w/ generation + crc32c)."""
    store = MagicMock()
    store.get_qa_artifact_info.return_value = (
        {
            "pdf": f"gs://arxiv-submit-dev/{SID}/{SID}.pdf#111",
            "source": f"gs://arxiv-submit-dev/{SID}/{SID}.tar.gz#222",
        },
        {"pdf": "PDFcrc==", "source": "SRCcrc=="},
    )
    return store


def _patch_api(monkeypatch, submission, categories, abs_cls, pg_cls):
    by_model = {
        Submission: [submission] if submission else [],
        SubmissionCategory: categories,
        SubmissionAbsClassifierDatum: [abs_cls] if abs_cls else [],
        SubmissionClassifierDatum: [pg_cls] if pg_cls else [],
    }
    api = MagicMock()
    api.get_session.return_value = _FakeSession(by_model)
    api.get_file_store.return_value = _fake_store()
    fake_app = MagicMock()
    fake_app.api = api
    monkeypatch.setattr(ctrl, "current_app", fake_app)


def test_build_qa_metadata_v12(monkeypatch):
    submission = Submission(
        submission_id=int(SID), type="new", source_format="tex", version=1,
        title="Towards End-to-End Automation", authors="Y. Yamada, C. Lu",
        abstract="An abstract.", comments=None, report_num=None,
        journal_ref=None, doi=None, msc_class=None, acm_class=None,
    )
    categories = [SubmissionCategory(submission_id=int(SID), category="cs.AI",
                                     is_primary=1, is_published=0)]
    abs_cls = SubmissionAbsClassifierDatum(
        submission_id=int(SID), status="success",
        json='{"classifier": [{"category": "cs.AI", "probability": 0.58}]}')
    pg_cls = SubmissionClassifierDatum(
        submission_id=int(SID), status="success",
        json='{"counts": {"pages": "182"}}')

    _patch_api(monkeypatch, submission, categories, abs_cls, pg_cls)

    out = ctrl.build_qa_metadata(SID)

    # --- schema version ---
    assert out["version"] == "1.2"
    assert out["name"] == "arXiv Submission Snapshot Metadata"

    # --- metadata_checksum: stringified adler32 of the descriptive metadata ---
    assert out["metadata_checksum"] == str(checksum_metadata(submission))

    # --- crc32c + urls (with generation) only for files that exist ---
    assert out["crc32c"] == {"pdf": "PDFcrc==", "source": "SRCcrc=="}
    assert out["urls"] == {
        "pdf": f"gs://arxiv-submit-dev/{SID}/{SID}.pdf#111",
        "source": f"gs://arxiv-submit-dev/{SID}/{SID}.tar.gz#222",
    }
    # urls carry the GS object generation suffix
    assert out["urls"]["pdf"].split("#")[-1] == "111"

    # --- arXiv_submissions: pinned column set, in order ---
    assert list(out["arXiv_submissions"]) == list(ARXIV_SUBMISSIONS_FIELDS)
    assert out["arXiv_submissions"]["submission_id"] == int(SID)
    assert out["arXiv_submissions"]["type"] == "new"

    # --- related tables; textual classifier json parsed into objects ---
    assert out["arXiv_submission_category"][0]["category"] == "cs.AI"
    assert out["arXiv_submission_near_duplicates"] == []
    assert isinstance(out["arXiv_submission_abs_classifier_data"]["json"], dict)
    assert out["arXiv_submission_classifier_data"]["json"] == {"counts": {"pages": "182"}}

    # whole doc must be JSON-serializable
    json.dumps(out)


def test_build_qa_metadata_no_files(monkeypatch):
    """When no artifacts exist, urls and crc32c are empty (not errors)."""
    submission = Submission(submission_id=int(SID), type="new", title="t",
                            authors="a", abstract="x")
    _patch_api(monkeypatch, submission, [], None, None)
    store = ctrl.current_app.api.get_file_store.return_value
    store.get_qa_artifact_info.return_value = ({}, {})

    out = ctrl.build_qa_metadata(SID)

    assert out["crc32c"] == {}
    assert out["urls"] == {}
    assert out["arXiv_submission_abs_classifier_data"] == {}
    assert out["arXiv_submission_classifier_data"] == {}
