"""Unit tests for `EmailSubmitterFinalizeMsg`.

These exercise the event's `execute` side effect directly with hand-built
submissions and stub APIs, so no app, DB, or file store is needed. Sending must
be non-fatal: a failure is recorded on `event.error`, never raised.
"""
from datetime import datetime

from pytz import UTC

from submit_ce.domain import agent
from submit_ce.domain.meta import Classification
from submit_ce.domain.config import SubmitConfig
from submit_ce.domain.event import EmailSubmitterFinalizeMsg
from submit_ce.domain.event.email import submitter_recipient
from submit_ce.domain.submission import Submission, SubmissionMetadata
from submit_ce.implementations.email.email_in_memory import EmailInMemory


def _user():
    return agent.PublicUser(name="Test User", user_id="u1",
                            email="submitter@example.org", endorsements=[])


def _submission():
    u = _user()
    return Submission(
        submission_id="12345",
        creator=u, owner=u, created=datetime.now(UTC),
        primary_classification=Classification(category="astro-ph.GA"),
        metadata=SubmissionMetadata(title="A Fine Paper"))


def _event():
    return EmailSubmitterFinalizeMsg(
        creator=agent.System(name="test"),
        email_to=_user(),
        submission_id="12345",
        created=datetime.now(UTC))


class _Api:
    """Minimal stub exposing get_email_service and get_config."""
    def __init__(self, service, config=None):
        self._service = service
        self._config = config or SubmitConfig(
            email_reply_to="replyhere@arxiv.org",
            url_for_user_dashboard="https://example.test/user/")

    def get_email_service(self):
        return self._service

    def get_config(self):
        return self._config


class _RaisingService(EmailInMemory):
    def send_email(self, *args, **kwargs):
        raise RuntimeError("smtp boom")


def test_execute_sends_confirmation_email():
    service = EmailInMemory()
    event = _event()
    event.execute(_Api(service), _submission())

    assert event.error is None
    assert len(service.sent) == 1
    sent = service.last
    assert sent.to == ["submitter@example.org"]
    assert sent.subject == "arXiv submission 12345"
    # Reply-To and dashboard URL come from api.get_config().
    assert sent.reply_to == "replyhere@arxiv.org"
    # Body interpolates the submitter name, temp id, title, and dashboard URL.
    assert "Dear Test User," in sent.body
    assert "12345" in sent.body
    assert "A Fine Paper" in sent.body
    assert "https://example.test/user/" in sent.body


def test_execute_with_no_service_records_error_and_does_not_raise():
    event = _event()
    event.execute(_Api(None), _submission())
    assert event.error is not None
    assert "not configured" in event.error


def test_execute_with_unavailable_service_does_not_send():
    class _Unavailable(EmailInMemory):
        def is_available(self):
            return False

    service = _Unavailable()
    event = _event()
    event.execute(_Api(service), _submission())
    assert len(service.sent) == 0
    assert event.error is not None


def test_execute_swallows_send_failure():
    """A raising email service must not propagate; error is recorded."""
    event = _event()
    event.execute(_Api(_RaisingService()), _submission())
    assert event.error is not None
    assert "smtp boom" in event.error


def test_execute_system_recipient_skips_send_without_error():
    """A System actor has no email address: skip the send, but it's not an error."""
    service = EmailInMemory()
    event = EmailSubmitterFinalizeMsg(
        creator=agent.System(name="sys"),
        email_to=agent.System(name="sys"),
        submission_id="12345",
        created=datetime.now(UTC))
    event.execute(_Api(service), _submission())
    assert len(service.sent) == 0
    assert event.error is None


def test_project_is_noop():
    sub = _submission()
    assert _event().project(sub) is sub


# --- recipient resolution (submitter_recipient) ---

def test_submitter_recipient_returns_user_name_and_email():
    """The recipient is the given user's name and email (the finalizer)."""
    assert submitter_recipient(_user()) == ("Test User",
                                            "submitter@example.org")


def test_submitter_recipient_staff_user():
    staff = agent.StaffUser(user_id="999", email="mod@arxiv.org",
                            name="Mod Erator", username="moderator")
    assert submitter_recipient(staff) == ("Mod Erator", "mod@arxiv.org")
