"""Phase 3: the oversize flag is projected to the classic DB columns.

Backward-compatibility contract: an oversize upload writes
``arXiv_submissions.is_oversize = 1`` (and leaves ``auto_hold = 0`` until
finalize), and the flag survives a domain -> DB -> domain round-trip.
"""

from flask import current_app
from arxiv.db import Session
from sqlalchemy import text


def _row(sid):
    return Session.execute(
        text("""
            SELECT is_oversize, auto_hold
            FROM arXiv_submissions
            WHERE submission_id = :sid
        """),
        {"sid": sid},
    ).fetchone()


def test_oversize_upload_writes_is_oversize_column(app, sub_files_oversize):
    with app.app_context():
        row = _row(sub_files_oversize.submission_id)
        assert row is not None
        assert row.is_oversize == 1
        # The auto-hold effect is not applied at upload time (unset/0).
        assert not row.auto_hold


def test_normal_upload_writes_is_oversize_zero(app, sub_files):
    with app.app_context():
        row = _row(sub_files.submission_id)
        assert row is not None
        assert row.is_oversize == 0


def test_is_oversize_round_trips(app, sub_files_oversize):
    """Reloading the submission reads the flag back from the DB column."""
    with app.app_context():
        reloaded = current_app.api.get(str(sub_files_oversize.submission_id))
        assert reloaded.is_oversize is True


def test_normal_submission_round_trips_false(app, sub_files):
    with app.app_context():
        reloaded = current_app.api.get(str(sub_files.submission_id))
        assert reloaded.is_oversize is False
