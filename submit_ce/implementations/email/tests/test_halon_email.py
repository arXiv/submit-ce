"""Tests for `HalonEmailService` and `SmtpCreds`, mocking the SMTP transport."""
import smtplib
from unittest import mock

import pytest

from submit_ce.implementations.email import HalonEmailService
from submit_ce.implementations.email.smtp_creds import SmtpCreds


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

    smtp_ssl.assert_called_once_with(host="mail.example.org", port=465, timeout=30.0)
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


@mock.patch("submit_ce.implementations.email.smtplib.SMTP")
def test_send_email_starttls_path(smtp):
    sess = smtp.return_value.__enter__.return_value
    service = HalonEmailService(
        host="smtp.example.org",
        user="u",
        password="p",
        from_address="noreply@arxiv.org",
        port=587,
        use_starttls=True,
    )
    service.send_email(["a@example.com"], "Hi", "Body", "reply@arxiv.org")

    smtp.assert_called_once_with(host="smtp.example.org", port=587, timeout=30.0)
    sess.starttls.assert_called_once()
    sess.login.assert_called_once_with("u", "p")
    sess.send_message.assert_called_once()


# --- send_email return value ---

@mock.patch("submit_ce.implementations.email.smtplib.SMTP_SSL")
def test_send_email_returns_message_id_and_empty_error_on_success(smtp_ssl):
    sess = smtp_ssl.return_value.__enter__.return_value
    sess.send_message.return_value = {}
    msg_id, err = make_service().send_email(
        ["a@example.com"], "Hi", "Body", "reply@arxiv.org",
        message_id="<fixed@arxiv.org>",
    )
    assert msg_id == "<fixed@arxiv.org>"
    assert err == ""


# --- send_email error paths ---

def _send(service=None, **kwargs):
    svc = service or make_service()
    return svc.send_email(["a@example.com"], "Hi", "Body", "reply@arxiv.org", **kwargs)


@mock.patch("submit_ce.implementations.email.smtplib.SMTP_SSL")
def test_send_email_timeout(smtp_ssl):
    smtp_ssl.side_effect = TimeoutError
    msg_id, err = _send()
    assert "timed out" in err
    assert "30.0" in err
    assert "mail.example.org" in err


@mock.patch("submit_ce.implementations.email.smtplib.SMTP_SSL")
def test_send_email_auth_failure(smtp_ssl):
    smtp_ssl.return_value.__enter__.return_value.login.side_effect = (
        smtplib.SMTPAuthenticationError(535, b"5.7.8 Bad credentials")
    )
    msg_id, err = _send()
    assert "authentication failed" in err
    assert "arxiv" in err  # user name included


@mock.patch("submit_ce.implementations.email.smtplib.SMTP_SSL")
def test_send_email_connect_error(smtp_ssl):
    smtp_ssl.return_value.__enter__.return_value.login.side_effect = (
        smtplib.SMTPConnectError(421, b"Service unavailable")
    )
    msg_id, err = _send()
    assert "connect" in err.lower()
    assert "mail.example.org" in err


@mock.patch("submit_ce.implementations.email.smtplib.SMTP_SSL")
def test_send_email_all_recipients_refused(smtp_ssl):
    smtp_ssl.return_value.__enter__.return_value.send_message.side_effect = (
        smtplib.SMTPRecipientsRefused({"a@example.com": (550, b"User unknown")})
    )
    msg_id, err = _send()
    assert "All recipients refused" in err
    assert "a@example.com" in err
    assert "550" in err


@mock.patch("submit_ce.implementations.email.smtplib.SMTP_SSL")
def test_send_email_sender_refused(smtp_ssl):
    smtp_ssl.return_value.__enter__.return_value.login.side_effect = (
        smtplib.SMTPSenderRefused(550, b"Sender denied", "noreply@arxiv.org")
    )
    msg_id, err = _send()
    assert "refused" in err.lower()
    assert "noreply@arxiv.org" in err


@mock.patch("submit_ce.implementations.email.smtplib.SMTP_SSL")
def test_send_email_partial_recipients_refused(smtp_ssl):
    sess = smtp_ssl.return_value.__enter__.return_value
    sess.send_message.return_value = {
        "bob@example.com": (550, b"User unknown"),
        "sam@example.com": (452, b"Mailbox full"),
    }
    msg_id, err = _send()
    assert "some recipients refused" in err
    assert "bob@example.com" in err
    assert "sam@example.com" in err
    assert "550" in err
    assert "452" in err


# --- SmtpCreds.parse ---

def test_parse_smtps_uri():
    creds = SmtpCreds.parse("smtps://arxiv:s3cr3t@mailh.arxiv.org:465")
    assert creds.host == "mailh.arxiv.org"
    assert creds.port == 465
    assert creds.user == "arxiv"
    assert creds.password == "s3cr3t"
    assert creds.use_ssl is True
    assert creds.use_starttls is False


def test_parse_starttls_uri():
    creds = SmtpCreds.parse("smtp+starttls://u:p@smtp.example.org:587")
    assert creds.use_ssl is False
    assert creds.use_starttls is True
    assert creds.port == 587


def test_parse_uri_no_port():
    creds = SmtpCreds.parse("smtps://u:p@mail.example.org")
    assert creds.port is None


def test_parse_uri_percent_encoded_password():
    creds = SmtpCreds.parse("smtps://user:p%40ssw%21rd@mail.example.org")
    assert creds.password == "p@ssw!rd"


def test_parse_uri_missing_hostname_raises():
    with pytest.raises(RuntimeError, match="hostname"):
        SmtpCreds.parse("smtps://")


