"""Persistence round-trip tests for category proposals.

Verifies that :class:`.ProposeClassification` records a row in the classic
``arXiv_submission_category_proposal`` table (with a linked admin-log comment)
and that the proposal is read back onto the domain submission.
"""

from flask import current_app
from arxiv.db import Session
from sqlalchemy import text

from submit_ce.domain.event import CreateSubmission, ProposeClassification
from submit_ce.domain.agent import InternalClient


def _create(user):
    client = InternalClient(name="test_proposal_persist")
    submission, _ = current_app.api.save(
        CreateSubmission(creator=user, client=client))
    return submission.submission_id, client


def test_propose_primary_persists_classic_row(app, authorized_user):
    """A primary proposal writes an UNRESOLVED row + admin-log comment."""
    with app.app_context():
        user = authorized_user
        sid, client = _create(user)

        submission, _ = current_app.api.save(
            ProposeClassification(creator=user, client=client,
                                  category="cs.AI", is_primary=True,
                                  comment="please reclassify"),
            submission_id=sid,
        )

        # Domain projection on the returned submission.
        assert any(p.category == "cs.AI" and p.is_primary and p.is_unresolved
                   for p in submission.proposals.values())

        row = Session.execute(text("""
            SELECT category, is_primary, proposal_status, user_id,
                   proposal_comment_id, response_comment_id
            FROM arXiv_submission_category_proposal
            WHERE submission_id = :sid
        """), {"sid": sid}).fetchone()
        assert row is not None
        assert row.category == "cs.AI"
        assert row.is_primary == 1
        assert row.proposal_status == 0      # UNRESOLVED
        assert row.user_id is not None
        assert row.response_comment_id is None
        assert row.proposal_comment_id is not None

        log_row = Session.execute(text("""
            SELECT logtext FROM arXiv_admin_log WHERE id = :id
        """), {"id": row.proposal_comment_id}).fetchone()
        assert log_row is not None
        assert "cs.AI" in log_row.logtext
        assert "primary" in log_row.logtext

        # Read-back via the API (to_submission).
        reloaded = current_app.api.get(str(sid))
        assert any(p.category == "cs.AI" and p.is_primary
                   for p in reloaded.proposals.values())


def test_propose_secondary_persists_is_primary_zero(app, authorized_user):
    """A cross-list proposal is stored with is_primary = 0."""
    with app.app_context():
        user = authorized_user
        sid, client = _create(user)

        current_app.api.save(
            ProposeClassification(creator=user, client=client,
                                  category="math.CO", is_primary=False),
            submission_id=sid,
        )

        row = Session.execute(text("""
            SELECT category, is_primary, proposal_status
            FROM arXiv_submission_category_proposal
            WHERE submission_id = :sid
        """), {"sid": sid}).fetchone()
        assert row is not None
        assert row.category == "math.CO"
        assert row.is_primary == 0
        assert row.proposal_status == 0
