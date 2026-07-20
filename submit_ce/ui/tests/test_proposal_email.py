"""End-to-end: making a proposal emails the category moderators.

Runs a real ``save`` through the app (which uses the in-memory email service in
TESTING mode) and asserts the moderator notification was sent. The moderators
are seeded by ``submit_ce.make_test_db.MODERATORS``.
"""

from flask import current_app

from submit_ce.domain.event import CreateSubmission, ProposeClassification
from submit_ce.domain.agent import InternalClient


def test_proposal_sends_moderator_email(app, authorized_user):
    with app.app_context():
        user = authorized_user
        client = InternalClient(name="test_proposal_email")

        service = current_app.api.email_service
        service.clear()

        submission, _ = current_app.api.save(
            CreateSubmission(creator=user, client=client))
        sid = submission.submission_id

        current_app.api.save(
            ProposeClassification(creator=user, client=client,
                                  category="math.AG", is_primary=False,
                                  comment="please reclassify"),
            submission_id=sid,
        )

        assert len(service.sent) == 1
        sent = service.last
        # math.AG category-level + math archive-level moderators, no opt-outs.
        assert sent.to == ["ag@example.org", "matharch@example.org"]
        assert sent.reply_to == \
            "MOD_ADMIN_EMAIL@example.org,ag@example.org,matharch@example.org"
        assert sent.bcc == ["LOCAL_ADMIN_EMAIL@example.org"]
        # Subject carries the submission id and submitter; the proposed
        # category appears in the body (the subject shows current categories).
        assert str(sid) in sent.subject
        assert "Proposed: math.AG as secondary" in sent.body
        # The submitter is never notified.
        assert "cs@example.org" not in sent.to
        assert "noweb@example.org" not in sent.to


def test_system_proposal_sends_no_email(app, authorized_user):
    """A system/classifier proposal does not email moderators."""
    from submit_ce.domain.agent import System

    with app.app_context():
        user = authorized_user
        client = InternalClient(name="test_proposal_email_sys")

        service = current_app.api.email_service
        service.clear()

        submission, _ = current_app.api.save(
            CreateSubmission(creator=user, client=client))
        sid = submission.submission_id

        current_app.api.save(
            ProposeClassification(creator=System(name="classifier"),
                                  category="math.AG", is_primary=False),
            submission_id=sid,
        )

        assert service.sent == []
