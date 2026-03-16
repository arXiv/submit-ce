"""Tests for :mod:`submit_ce.controllers.jref` - test for unconfirmed changed."""
import pytest
from types import SimpleNamespace
from werkzeug.datastructures import MultiDict
from submit_ce.ui.controllers.jref import jref

@pytest.mark.usefixtures("app")
def test_jref_post_valid_but_unconfirmed(monkeypatch):
    class Meta: doi=None; journal_ref=None; report_num=None
    class Sub: is_announced=True; metadata=Meta()

    # Patch where the controller looks these up
    monkeypatch.setattr("submit_ce.ui.controllers.jref.get_submission",
                        lambda sid: (Sub(), []))
    monkeypatch.setattr("submit_ce.ui.controllers.jref.user_and_client_from_session",
                        lambda session: ("creator", "client"))

    # CSRF: provide config & request stub
    monkeypatch.setattr(
        "arxiv.forms.csrf.get_application_config",
        lambda: {"CSRF_SECRET": "test-secret"},
        raising=False
    )
    req_stub = SimpleNamespace(
        auth=None,
        session=SimpleNamespace(nonce="test-nonce", session_id="sid-1"),
        remote_addr="127.0.0.1",
    )
    monkeypatch.setattr("arxiv.forms.csrf.request", req_stub, raising=False)

    # Bypass CSRF/form validation for this unit test
    monkeypatch.setattr(
        "submit_ce.ui.controllers.jref.JREFForm.validate",
        lambda self: True
    )

    # Guard: save() MUST NOT run when not confirmed
    class DummyAPI:
        def save(self, *args, **kwargs):
            raise AssertionError("save() must not be called when not confirmed")
    class DummyApp: api = DummyAPI()
    monkeypatch.setattr("submit_ce.ui.controllers.jref.current_app", DummyApp())

    class Session: ...
    params = MultiDict({
        "doi": "10.1234/abcd",
        "confirmed": "",   # in BooleanField.false_values -> False
    })

    data, code, headers = jref("POST", params, Session(), submission_id=1)

    assert code == 200
    assert headers == {}
    assert data.get("require_confirmation") is True
