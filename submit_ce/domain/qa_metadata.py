"""Build the QA "submission snapshot" metadata document.

This mirrors the generator in
``arxiv-qa/snapshot_submission/snapshot_submission/snapshot_submission.py``: a
JSON snapshot of the legacy ``arXiv_submissions`` row and related tables that the
QA pipeline reads from ``<id>/<id>.meta.json``. The top-level keys are the names
of the originating database tables. See SUBMISSION-136.

Schema version history (from the QA generator):
- 1.0 (2021-08): had ``arXiv_admin_log``, lacked ``urls``.
- 1.1 (2025-10): dropped ``arXiv_admin_log``, added GS ``urls``.
- 1.2 (2026-02): added ``metadata_checksum`` and per-file ``crc32c``.

This module works on plain column dicts (not ORM objects) so the domain layer
stays free of any database/implementation coupling; the caller is responsible
for turning DB rows into dicts (datetimes already ISO-formatted) and for
computing the GS ``urls``/``crc32c`` and ``metadata_checksum``. Parsing of the
textual ``json`` columns is handled here.
"""
import json
from typing import Any, Iterable, Mapping, Optional

SNAPSHOT_NAME = "arXiv Submission Snapshot Metadata"
SNAPSHOT_VERSION = "1.2"

#: The ``arXiv_submissions`` columns included in the snapshot, in order. The DB
#: model carries extra processing columns (``data_version``, ``preflight``, ...)
#: that the QA snapshot deliberately omits; pinning the list keeps the output
#: stable and matching the legacy snapshot tool.
ARXIV_SUBMISSIONS_FIELDS = (
    "submission_id", "document_id", "doc_paper_id", "sword_id", "userinfo",
    "is_author", "agree_policy", "viewed", "stage", "submitter_id",
    "submitter_name", "submitter_email", "created", "updated", "status",
    "sticky_status", "must_process", "submit_time", "release_time",
    "source_size", "source_format", "source_flags", "has_pilot_data",
    "is_withdrawn", "title", "authors", "comments", "proxy", "report_num",
    "msc_class", "acm_class", "journal_ref", "doi", "abstract", "license",
    "version", "type", "is_ok", "admin_ok", "allow_tex_produced",
    "is_oversize", "remote_addr", "remote_host", "package", "rt_ticket_id",
    "auto_hold", "is_locked", "agreement_id",
)


def _classifier_data(row: Optional[Mapping[str, Any]]) -> dict:
    """Return a classifier-data dict with its textual ``json`` column parsed."""
    if not row:
        return {}
    out = dict(row)
    if out.get("json"):
        out["json"] = json.loads(out["json"])
    return out


def build_snapshot(
    submission: Mapping[str, Any],
    categories: Iterable[Mapping[str, Any]],
    near_duplicates: Iterable[Mapping[str, Any]],
    abs_classifier: Optional[Mapping[str, Any]],
    classifier: Optional[Mapping[str, Any]],
    metadata_checksum: Any,
    urls: Optional[Mapping[str, str]] = None,
    crc32c: Optional[Mapping[str, str]] = None,
) -> dict:
    """Assemble the QA submission-snapshot document (schema version 1.2).

    Parameters are column dicts for the corresponding ``arXiv_submission*``
    tables (``submission`` is the ``arXiv_submissions`` row). ``metadata_checksum``
    is the adler32 of the descriptive metadata (stringified to match the QA
    generator); ``urls`` maps artifact names to their GCS locations and
    ``crc32c`` maps the same names to each blob's crc32c checksum.
    """
    return {
        "name": SNAPSHOT_NAME,
        "version": SNAPSHOT_VERSION,
        "arXiv_submissions": {f: submission.get(f) for f in ARXIV_SUBMISSIONS_FIELDS},
        "arXiv_submission_category": [dict(c) for c in categories],
        "arXiv_submission_near_duplicates": [dict(n) for n in near_duplicates],
        "arXiv_submission_abs_classifier_data": _classifier_data(abs_classifier),
        "arXiv_submission_classifier_data": _classifier_data(classifier),
        "metadata_checksum": str(metadata_checksum),
        "urls": dict(urls) if urls else {},
        "crc32c": dict(crc32c) if crc32c else {},
    }
