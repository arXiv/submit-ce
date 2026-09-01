"""Build the QA "submission snapshot" metadata for a submission.

Reads the legacy ``arXiv_submissions`` row and related tables and assembles the
snapshot the QA pipeline consumes (the ``<id>/<id>.meta.json`` document).
Equivalent to ``arxiv-qa/metadata/snapshot_md.py``. The pure assembly/schema
lives in :mod:`submit_ce.domain.qa_metadata`; this module does the DB queries
and ORM-row-to-dict plumbing. See SUBMISSION-136.
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
from qa.checks.utils.checksum import checksum_metadata

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
        # satisfies qa.checks.models.MetadataProtocol) before it is flattened.
        metadata_checksum = checksum_metadata(submission)

        urls, crc32c = current_app.api.get_file_store().get_qa_artifact_info(submission_id)

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
