"""Tests for :mod:`submit_ce.controllers.jref` - confirmed changes trigger save."""
import pytest
from types import SimpleNamespace
from unittest import mock
from werkzeug.datastructures import MultiDict
from http import HTTPStatus as status

from flask import current_app
from submit_ce.ui.controllers.jref import jref
from submit_ce.api.domain.agent import InternalClient


@pytest.mark.usefixtures("app")
def test_jref_post_confirmed_changed_saves_and_redirects(monkeypatch, authorized_user, app):
    # Build a submission that is announced with old metadata
    class Meta:
        doi = "10.1/old"; journal_ref = "Old JR"; report_num = "RN-1"
    class Sub:
        is_announced = True
        metadata = Meta()

    # Return real domain objects, not strings
    monkeypatch.setattr(
        "submit_ce.ui.controllers.jref.user_and_client_from_session",
        lambda session: (authorized_user, InternalClient(name="test-client"))
    )

    # Controller-namespace patches
    monkeypatch.setattr("submit_ce.ui.controllers.jref.get_submission", lambda sid: (Sub(), []))
    monkeypatch.setattr("submit_ce.ui.controllers.jref.url_for", lambda *a, **k: "/url/for/create-submission")
    monkeypatch.setattr("submit_ce.ui.controllers.jref.alerts.flash_success", lambda *a, **k: None)

    # Disable CSRF / make form validate()
    monkeypatch.setattr("arxiv.forms.csrf.get_application_config",
                        lambda: {"CSRF_SECRET": "test-secret"}, raising=False)
    req_stub = SimpleNamespace(
        auth=None,
        session=SimpleNamespace(nonce="test-nonce", session_id="sid-1"),
        remote_addr="127.0.0.1",
    )
    monkeypatch.setattr("arxiv.forms.csrf.request", req_stub, raising=False)
    monkeypatch.setattr("submit_ce.ui.controllers.jref.JREFForm.validate", lambda self: True)

    # validators return True to allow save to proceed
    monkeypatch.setattr("submit_ce.ui.controllers.jref.validate_command", lambda *a, **k: True)

    # Fake save updates the submission metadata and returns (submission, events)
    def _fake_save(*events, submission_id=None):
        new = mock.MagicMock()
        md = SimpleNamespace(doi="10.1/new", journal_ref="New JR", report_num="RN-2")
        new.metadata = md
        new.is_announced = True
        return new, list(events)

    # Patch current_app.api inside an app context so the proxy resolves
    with app.app_context():
        current_app.api = mock.MagicMock()
        current_app.api.save.side_effect = _fake_save

        params = MultiDict({
            "doi": "10.1/new",
            "journal_ref": "New JR",
            "report_num": "RN-2",
            "confirmed": "1",  # True → proceed to save
        })

        data, code, headers = jref("POST", params, object(), submission_id=123)

    assert code == status.SEE_OTHER
    assert headers.get("Location") == "/url/for/create-submission"

