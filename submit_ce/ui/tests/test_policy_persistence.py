from datetime import datetime
from pytz import UTC
from flask import current_app
from arxiv.db import Session
from sqlalchemy import text

from submit_ce.domain.event import ConfirmPolicy, CreateSubmission
from submit_ce.domain.agent import InternalClient

def test_confirm_policy_persists_agreement_id(app, authorized_user):
    """Ensure ConfirmPolicy writes agree_policy=1 and agreement_id=X into classic DB."""
    with app.app_context():
        user = authorized_user
        client = InternalClient(name="test_policy_persist")

        # 1. Create a new submission
        submission, _ = current_app.api.save(
            CreateSubmission(creator=user, client=client)
        )
        sid = submission.submission_id

        # 2. Apply ConfirmPolicy with agreement_id
        submission, _ = current_app.api.save(
            ConfirmPolicy(
                creator=user,
                client=client,
                agreement_id=42
            ),
            submission_id=sid
        )

        # 3. Query classic DB directly
        row = Session.execute(
            text("""
                        SELECT agree_policy, agreement_id
                        FROM arXiv_submissions
                        WHERE submission_id = :sid
                    """),
            {"sid": sid}
        ).fetchone()

        assert row is not None
        assert row.agree_policy == 1
        assert row.agreement_id == 42

