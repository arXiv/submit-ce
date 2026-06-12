"""Unit tests for backend.email_service_from_settings (EMAIL_MODE switch)."""
from types import SimpleNamespace

from submit_ce.ui.backend import email_service_from_settings
from submit_ce.implementations.email import HalonEmailService
from submit_ce.implementations.email.email_in_memory import EmailInMemory


def _halon_settings(mode):
    return SimpleNamespace(
        EMAIL_MODE=mode,
        EMAIL_SMTP_HOST="h",
        EMAIL_SMTP_PORT=465,
        EMAIL_SMTP_USER="u",
        EMAIL_SMTP_PASSWORD="p",
        EMAIL_FROM="from@arxiv.org",
    )


def test_testing_mode_returns_in_memory():
    service = email_service_from_settings(SimpleNamespace(EMAIL_MODE="TESTING"))
    assert isinstance(service, EmailInMemory)


def test_halon_mode_builds_halon_from_settings():
    service = email_service_from_settings(_halon_settings("HALON"))
    assert isinstance(service, HalonEmailService)
    assert service.host == "h"
    assert service.port == 465
    assert service.user == "u"
    assert service.from_address == "from@arxiv.org"
