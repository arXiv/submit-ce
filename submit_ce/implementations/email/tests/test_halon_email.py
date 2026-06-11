"""Tests for `HalonEmailService`, mocking the SMTP transport."""
from unittest import mock

from submit_ce.implementations.email import (
    HalonEmailService,
    email_service_from_settings,
)


def make_service() -> HalonEmailService:
    return HalonEmailService(
        host="mail.example.org",
        user="arxiv",
        password="secret",
        from_address="noreply@arxiv.org",
        port=465,
    )


@mock.patch("submit_ce.implementations.email.smtplib.SMTP_SSL")
def test_send_email_logs_in_and_sends(smtp_ssl):
    sess = smtp_ssl.return_value.__enter__.return_value
    service = make_service()

    service.send_email(
        to=["a@example.com", "b@example.com"],
        subject="Hello",
        body="A body\n",
        reply_to="reply@arxiv.org",
        cc=["c@example.com"],
        bcc=["d@example.com"],
        message_id="<id@arxiv.org>",
        references="<prev@arxiv.org>",
    )

    smtp_ssl.assert_called_once_with(host="mail.example.org", port=465)
    sess.login.assert_called_once_with("arxiv", "secret")

    assert sess.send_message.call_count == 1
    _, kwargs = sess.send_message.call_args
    msg = sess.send_message.call_args.args[0]

    # Envelope includes To + Cc + Bcc recipients.
    assert kwargs["from_addr"] == "noreply@arxiv.org"
    assert kwargs["to_addrs"] == [
        "a@example.com", "b@example.com", "c@example.com", "d@example.com",
    ]
    assert kwargs["mail_options"] == ("8bitmime",)

    # Headers.
    assert msg["From"] == "noreply@arxiv.org"
    assert msg["To"] == "a@example.com, b@example.com"
    assert msg["Cc"] == "c@example.com"
    assert msg["Subject"] == "Hello"
    assert msg["Reply-To"] == "reply@arxiv.org"
    assert msg["Message-ID"] == "<id@arxiv.org>"
    assert msg["References"] == "<prev@arxiv.org>"
    # Bcc is an envelope recipient only, never a header.
    assert msg["Bcc"] is None
    assert msg.get_content() == "A body\n"


@mock.patch("submit_ce.implementations.email.smtplib.SMTP_SSL")
def test_send_email_generates_message_id_when_absent(smtp_ssl):
    service = make_service()
    service.send_email(["a@example.com"], "Hi", "Body", "reply@arxiv.org")

    msg = smtp_ssl.return_value.__enter__.return_value.send_message.call_args.args[0]
    assert msg["Message-ID"]  # auto-generated, non-empty
    assert msg["Cc"] is None
    assert msg["References"] is None


def test_is_available_requires_full_config():
    assert make_service().is_available() is True
    assert HalonEmailService("h", "u", "", "f@x.org").is_available() is False
    assert HalonEmailService("", "u", "p", "f@x.org").is_available() is False


def test_repr_hides_password():
    assert "secret" not in repr(make_service())


def test_email_service_from_settings_uses_settings():
    settings = mock.Mock(
        EMAIL_SMTP_HOST="h",
        EMAIL_SMTP_PORT=465,
        EMAIL_SMTP_USER="u",
        EMAIL_SMTP_PASSWORD="p",
        EMAIL_FROM="from@arxiv.org",
    )
    service = email_service_from_settings(settings)
    assert service.host == "h"
    assert service.from_address == "from@arxiv.org"
