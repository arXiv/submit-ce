"""Debug controller: build the QA "submission snapshot" metadata.

Reads the legacy ``arXiv_submissions`` row and related tables for a submission
and assembles the snapshot the QA pipeline consumes (the ``<id>/<id>.meta.json``
document). Equivalent to ``arxiv-qa/metadata/snapshot_md.py``. Used to verify
SUBMISSION-136 parity. See :mod:`submit_ce.domain.qa_metadata`.
"""
from datetime import datetime
from typing import Any, Dict

from flask import current_app
from sqlalchemy.orm import class_mapper
from werkzeug.exceptions import NotFound

from arxiv.base import logging
from arxiv.db.models import (
    Submission,
    SubmissionCategory,
    SubmissionNearDuplicate,
    SubmissionAbsClassifierDatum,
    SubmissionClassifierDatum,
)

from submit_ce.domain import qa_metadata

logger = logging.getLogger(__name__)


def _row_to_dict(row: Any) -> Dict[str, Any]:
    """Serialize a SQLAlchemy row to a dict of its columns (datetimes -> ISO)."""
    columns = [c.key for c in class_mapper(row.__class__).columns]
    out: Dict[str, Any] = {}
    for col in columns:
        value = getattr(row, col)
        out[col] = value.isoformat() if isinstance(value, datetime) else value
    return out


def _urls(store: Any, submission_id: str) -> Dict[str, str]:
    """Best-effort map of submission artifact name -> ``gs://`` path.

    The legacy snapshot appends a ``#<generation>`` suffix to each URL; that is
    omitted here since this is a debug view and listing each blob's generation
    is unnecessary. Returns ``{}`` if the store does not expose GCS paths.
    """
    try:
        base = store.get_full_submission_path(submission_id)
    except Exception:  # e.g. NullFileStore has no gs:// layout
        return {}
    return {
        "pdf": f"{base}/{submission_id}.pdf",
        "source": f"{base}/{submission_id}.tar.gz",
        "directives.json": f"{base}/directives.json",
        "gcp_compile.json": f"{base}/gcp_compile.json",
        "gcp_compile.log": f"{base}/gcp_compile.log",
        "gcp_preflight.json": f"{base}/gcp_preflight.json",
        "source.log": f"{base}/source.log",
    }


def build_qa_metadata(submission_id: str) -> Dict[str, Any]:
    """Query the legacy submission tables and build the QA snapshot dict."""
    sid = int(submission_id)
    with current_app.api.get_session() as session:
        submission = (session.query(Submission)
                      .filter(Submission.submission_id == sid).first())
        if submission is None:
            raise NotFound(f"No arXiv_submissions row for {submission_id}")

        categories = (session.query(SubmissionCategory)
                      .filter(SubmissionCategory.submission_id == sid).all())
        near_duplicates = (session.query(SubmissionNearDuplicate)
                           .filter(SubmissionNearDuplicate.submission_id == sid).all())
        abs_classifier = (session.query(SubmissionAbsClassifierDatum)
                          .filter(SubmissionAbsClassifierDatum.submission_id == sid).first())
        classifier = (session.query(SubmissionClassifierDatum)
                      .filter(SubmissionClassifierDatum.submission_id == sid).first())

        return qa_metadata.build_snapshot(
            submission=_row_to_dict(submission),
            categories=[_row_to_dict(c) for c in categories],
            near_duplicates=[_row_to_dict(n) for n in near_duplicates],
            abs_classifier=_row_to_dict(abs_classifier) if abs_classifier else None,
            classifier=_row_to_dict(classifier) if classifier else None,
            urls=_urls(current_app.api.get_file_store(), submission_id),
        )
