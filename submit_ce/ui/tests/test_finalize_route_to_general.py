"""End-to-end: finalize routes a flagged submitter to a general category.

SUBMISSION-39. As legacy ``route_to_gen`` does, a ``GENPH`` pattern in
``arXiv_suspect_emails`` that matches the submitter's email moves a new
submission to its general category when it is submitted. The pattern matching
itself is tested in ``legacy_implementation/tests/test_suspect.py``.
"""
import re
from datetime import datetime, UTC

import arxiv.db.models as classic
import pytest
from arxiv.db import Session
from flask import current_app
from sqlalchemy import delete, select

from submit_ce.domain.agent import InternalClient
from submit_ce.domain.event import AddSecondaryClassification, FinalizeSubmission, \
    RouteToGeneralCategory
from submit_ce.implementations.email.email_in_memory import EmailInMemory
from submit_ce.implementations.legacy_implementation.models import AdminLogEntry

UA = InternalClient(name="test_client_route_to_general")


@pytest.fixture
def genph_pattern(app, authorized_user):
    """A ``GENPH`` pattern for the test user's address, removed afterwards."""
    pattern = re.escape(authorized_user.email).replace("@", r"\@")
    with app.app_context():
        row = classic.SuspectEmail(type="GENPH", pattern=pattern,
                                   comment=__name__, updated=datetime.now(UTC))
        Session.add(row)
        Session.commit()
        row_id = row.id
    yield
    with app.app_context():
        Session.execute(delete(classic.SuspectEmail).where(classic.SuspectEmail.id == row_id))
        Session.commit()


def _finalize(user, sid):
    service = EmailInMemory()
    original = current_app.api.email_service
    current_app.api.email_service = service
    try:
        current_app.api.save(FinalizeSubmission(creator=user, client=UA),
                             submission_id=sid)
    finally:
        current_app.api.email_service = original
    return current_app.api.get(str(sid)), service.sent


def _route_logs(sid):
    return Session.scalars(select(AdminLogEntry).where(
        AdminLogEntry.submission_id == int(sid),
        AdminLogEntry.logtext == "route to gen")).all()


def test_matching_submitter_is_routed(app, authorized_user, sub_metadata, genph_pattern):
    with app.app_context():
        sid = sub_metadata.submission_id
        current_app.api.save(
            AddSecondaryClassification(creator=authorized_user, client=UA,
                                       category="gr-qc"),
            submission_id=sid)

        submission, sent = _finalize(authorized_user, sid)

        assert submission.primary_category == "physics.gen-ph"
        assert submission.secondary_categories == []
        [log] = _route_logs(sid)
        assert (log.program, log.command, log.username) == ("Submission", "submit", "foouser")
        assert any(e.subject.startswith(f"arXiv submission {sid} to physics.gen-ph by")
                   for e in sent)
        _, history = current_app.api.get_with_history(str(sid))
        assert [e.category for e in history
                if isinstance(e, RouteToGeneralCategory)] == ["physics.gen-ph"]


def test_admin_submitter_is_not_routed(app, authorized_user, sub_metadata, genph_pattern):
    with app.app_context():
        sid = sub_metadata.submission_id
        user_id = int(authorized_user.user_id)
        tapir_user = Session.get(classic.TapirUser, user_id)
        was_admin = tapir_user.flag_edit_users
        tapir_user.flag_edit_users = 1
        Session.commit()
        try:
            submission, _ = _finalize(authorized_user, sid)
        finally:  # save() closes the session, so load the user again
            Session.get(classic.TapirUser, user_id).flag_edit_users = was_admin
            Session.commit()

        assert submission.primary_category == "astro-ph.GA"
        assert submission.secondary_categories == ["astro-ph.CO"]
        assert _route_logs(sid) == []
