"""Tests for the /debug/mail email viewer route."""
from submit_ce.implementations.email.email_in_memory import EmailInMemory


def test_debug_mail_shows_captured_email(app, admin_client):
    with app.app_context():
        service = app.api.get_email_service()
        assert isinstance(service, EmailInMemory)
        service.clear()
        service.send_email(["someone@example.com"], "Hello there",
                           "This is the body of the message.",
                           "noreply@arxiv.org")

    resp = admin_client.get('/debug/mail')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'someone@example.com' in body
    assert 'Hello there' in body
    assert 'This is the body of the message.' in body


def test_debug_mail_empty(app, admin_client):
    with app.app_context():
        app.api.get_email_service().clear()

    resp = admin_client.get('/debug/mail')
    assert resp.status_code == 200
    assert 'No email has been captured yet.' in resp.get_data(as_text=True)


def test_debug_mail_404_when_not_testing_mode(app, admin_client):
    from submit_ce.ui.config import settings
    original = settings.EMAIL_MODE
    settings.EMAIL_MODE = "HALON"
    try:
        resp = admin_client.get('/debug/mail')
        assert resp.status_code == 404
    finally:
        settings.EMAIL_MODE = original


def test_debug_mail_requires_auth(app):
    """Unauthenticated requests are rejected by the global auth check."""
    resp = app.test_client().get('/debug/mail')
    assert resp.status_code == 401


def test_debug_mail_requires_auth_with_halon(app):
    from submit_ce.ui.config import settings
    original = settings.EMAIL_MODE
    settings.EMAIL_MODE = "HALON"
    try:
        resp = app.test_client().get('/debug/mail')
        assert resp.status_code == 401
    finally:
        settings.EMAIL_MODE = original
