"""Build the QA "submission snapshot" metadata for a submission.

Reads the legacy ``arXiv_submissions`` row and related tables and assembles the
snapshot the QA pipeline consumes (the ``<id>/<id>.meta.json`` document).
Equivalent to ``arxiv-qa/metadata/snapshot_md.py``. The pure assembly/schema
lives in :mod:`submit_ce.domain.qa_metadata`; this module does the DB queries
and ORM-row-to-dict plumbing. See SUBMISSION-136.
"""
from datetime import datetime
from typing import Any, Dict, Tuple

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
from arxiv.metadata.checksum import checksum_metadata

from submit_ce.domain import qa_metadata

logger = logging.getLogger(__name__)

#: QA snapshot artifact key -> (filename under the submission dir, file-store
#: checksum method). The checksum method returns the blob's crc32c, or "" when
#: the file does not exist. Mirrors ``upload_submission_files`` in the QA
#: generator (arxiv-qa snapshot_submission).
_QA_ARTIFACTS: Tuple[Tuple[str, str, str], ...] = (
    ("pdf", "{sid}.pdf", "get_preview_checksum"),
    ("source", "{sid}.tar.gz", "get_source_package_checksum"),
    ("directives.json", "directives.json", "get_directives_checksum"),
    ("gcp-compile.json", "gcp_compile.json", "get_compile_json_checksum"),
    ("gcp_compile.log", "gcp_compile.log", "get_compile_log_checksum"),
    ("gcp_preflight.json", "gcp_preflight.json", "get_preflight_checksum"),
    ("source.log", "source.log", "get_source_log_checksum"),
)


def _row_to_dict(row: Any) -> Dict[str, Any]:
    """Serialize a SQLAlchemy row to a dict of its columns (datetimes -> ISO)."""
    columns = [c.key for c in class_mapper(row.__class__).columns]
    out: Dict[str, Any] = {}
    for col in columns:
        value = getattr(row, col)
        out[col] = value.isoformat() if isinstance(value, datetime) else value
    return out


def _urls_and_crc32c(store: Any, submission_id: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Map artifact name -> ``gs://`` path and -> crc32c, for files that exist.

    crc32c comes from the file store's ``get_*_checksum`` methods (each returns
    the blob's crc32c, or "" when absent). Only artifacts with a non-empty
    crc32c are included, matching the QA generator which omits missing files.
    Returns ``({}, {})`` if the store does not expose GCS paths.
    """
    try:
        base = store.get_full_submission_path(submission_id)
    except Exception:  # e.g. NullFileStore has no gs:// layout
        return {}, {}
    urls: Dict[str, str] = {}
    crc32c: Dict[str, str] = {}
    for key, filename_tmpl, checksum_method in _QA_ARTIFACTS:
        method = getattr(store, checksum_method, None)
        if method is None:
            continue
        crc = method(submission_id)
        if not crc:  # empty string => file not present; skip like the QA tool
            continue
        filename = filename_tmpl.format(sid=submission_id)
        urls[key] = f"{base}/{filename}"
        crc32c[key] = crc
    return urls, crc32c


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

        # adler32 of descriptive metadata; computed from the ORM row (which
        # satisfies arxiv.metadata.MetadataProtocol) before it is flattened.
        metadata_checksum = checksum_metadata(submission)

        urls, crc32c = _urls_and_crc32c(current_app.api.get_file_store(), submission_id)

        return qa_metadata.build_snapshot(
            submission=_row_to_dict(submission),
            categories=[_row_to_dict(c) for c in categories],
            near_duplicates=[_row_to_dict(n) for n in near_duplicates],
            abs_classifier=_row_to_dict(abs_classifier) if abs_classifier else None,
            classifier=_row_to_dict(classifier) if classifier else None,
            metadata_checksum=metadata_checksum,
            urls=urls,
            crc32c=crc32c,
        )
