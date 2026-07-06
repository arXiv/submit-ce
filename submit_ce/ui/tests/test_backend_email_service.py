"""Unit tests for backend.email_service_from_settings (EMAIL_MODE switch)."""
from types import SimpleNamespace
from unittest import mock

from submit_ce.ui.backend import email_service_from_settings
from submit_ce.implementations.email import HalonEmailService
from submit_ce.implementations.email.email_in_memory import EmailInMemory
from submit_ce.implementations.email.smtp_creds import SmtpCreds


def _halon_settings(mode="HALON"):
    return SimpleNamespace(
        EMAIL_MODE=mode,
        EMAIL_SMTP_SECRET="MY_SECRET",
        EMAIL_FROM="from@arxiv.org",
        EMAIL_TIMEOUT=30.0,
    )


def _ssl_creds():
    return SmtpCreds(
        host="mail.example.org",
        port=465,
        user="u",
        password="p",
        use_ssl=True,
        use_starttls=False,
    )


def test_testing_mode_returns_in_memory():
    service = email_service_from_settings(SimpleNamespace(EMAIL_MODE="TESTING"))
    assert isinstance(service, EmailInMemory)


def test_halon_mode_fetches_secret_and_builds_service():
    with mock.patch(
        "submit_ce.ui.backend.smtp_creds_from_secret", return_value=_ssl_creds()
    ) as mock_fetch:
        service = email_service_from_settings(_halon_settings())

    mock_fetch.assert_called_once_with("MY_SECRET")
    assert isinstance(service, HalonEmailService)
    assert service.host == "mail.example.org"
    assert service.port == 465
    assert service.user == "u"
    assert service.from_address == "from@arxiv.org"
    assert service.use_starttls is False


def test_halon_mode_starttls_creds():
    starttls_creds = SmtpCreds(
        host="smtp.example.org",
        port=587,
        user="u",
        password="p",
        use_ssl=False,
        use_starttls=True,
    )
    with mock.patch(
        "submit_ce.ui.backend.smtp_creds_from_secret", return_value=starttls_creds
    ):
        service = email_service_from_settings(_halon_settings())

    assert service.use_starttls is True
    assert service.port == 587


def test_halon_mode_falls_back_to_port_465_when_uri_has_no_port():
    no_port_creds = SmtpCreds(
        host="mail.example.org",
        port=None,
        user="u",
        password="p",
        use_ssl=True,
        use_starttls=False,
    )
    with mock.patch(
        "submit_ce.ui.backend.smtp_creds_from_secret", return_value=no_port_creds
    ):
        service = email_service_from_settings(_halon_settings())

    assert service.port == 465
