"""End-to-end: finalizing a submission emails the submitter.

Exercises the Event.consequences() mechanism through the real save loop:
FinalizeSubmission declares EmailSubmitterFinalizeMsg as a consequence and emits
it on finalize; the save loop executes the side effect (sending the email) in
the same transaction. We swap in an EmailInMemory service to capture the send.
"""
from flask import current_app

from submit_ce.domain.agent import InternalClient
from submit_ce.domain.event import FinalizeSubmission, EmailSubmitterFinalizeMsg
from submit_ce.domain.submission import Submission
from submit_ce.implementations.email.email_in_memory import EmailInMemory


def test_finalize_sends_submitter_email(app, authorized_user, sub_metadata):
    """Finalizing captures exactly one confirmation email to the submitter."""
    with app.app_context():
        user = authorized_user
        ua = InternalClient(name="test_client_finalize_email")
        sid = sub_metadata.submission_id

        service = EmailInMemory()
        original = current_app.api.email_service
        current_app.api.email_service = service
        try:
            submission, _ = current_app.api.save(
                FinalizeSubmission(creator=user, client=ua), submission_id=sid)
        finally:
            current_app.api.email_service = original

        assert submission.status == Submission.SUBMITTED
        assert len(service.sent) == 1
        sent = service.last
        assert sent.to == [submission.contact_email]
        assert sent.subject == f"arXiv submission {sid}"
        # Reply-To and dashboard URL are resolved from SubmitConfig, which the
        # backend builds from settings (BASE_SERVER substituted into the URL).
        assert sent.reply_to == "EMAIL_REPLY_TO@example.org"
        assert "/user/" in sent.body
        assert current_app.api.get_config().url_for_user_dashboard in sent.body

        # The consequence is persisted as a real event in the history.
        _, history = current_app.api.get_with_history(str(sid))
        assert any(isinstance(e, EmailSubmitterFinalizeMsg) for e in history)


def test_finalize_email_failure_is_non_fatal(app, authorized_user, sub_metadata):
    """A failing email send must not abort the finalize transaction."""
    class _RaisingService(EmailInMemory):
        def send_email(self, *args, **kwargs):
            raise RuntimeError("smtp boom")

    with app.app_context():
        user = authorized_user
        ua = InternalClient(name="test_client_finalize_email")
        sid = sub_metadata.submission_id

        original = current_app.api.email_service
        current_app.api.email_service = _RaisingService()
        try:
            submission, _ = current_app.api.save(
                FinalizeSubmission(creator=user, client=ua), submission_id=sid)
        finally:
            current_app.api.email_service = original

        # Submit still succeeded despite the email failure.
        assert submission.status == Submission.SUBMITTED
        _, history = current_app.api.get_with_history(str(sid))
        emails = [e for e in history
                  if isinstance(e, EmailSubmitterFinalizeMsg)]
        assert len(emails) == 1
        assert emails[0].error is not None
