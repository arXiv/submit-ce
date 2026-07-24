"""Tests for :mod:`submit_ce.controllers.jref` - test that confirmed but unchanged is noop."""
import pytest
from types import SimpleNamespace
from werkzeug.datastructures import MultiDict
from submit_ce.ui.controllers.jref import jref

@pytest.mark.usefixtures("app")
def test_jref_post_confirmed_but_unchanged(monkeypatch):
    class Meta:
        doi = "10.9999/existing"
        journal_ref = "Nucl.Phys.Proc.Suppl. 109 (2002) 3-9"
        report_num = "SU-4240-720"
    class Sub:
        is_announced=True
        arxiv_id="1234.5678"
        metadata=Meta()

    # Controller-namespace patches
    monkeypatch.setattr("submit_ce.ui.controllers.jref.get_submission",
                        lambda sid: (Sub(), []))
    monkeypatch.setattr("submit_ce.ui.controllers.jref.require_no_active_submission",
                        lambda *a, **k: None)
    monkeypatch.setattr("submit_ce.ui.controllers.jref.user_and_client_from_session",
                        lambda session: ("creator", "client"))

    # CSRF pieces to allow form construction
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

    # Guard: save must NOT be called on no-op post
    class DummyAPI:
        def save(self, *args, **kwargs):
            raise AssertionError("save() must not be called for no-op POST")
    class DummyApp:
        api = DummyAPI()
    monkeypatch.setattr("submit_ce.ui.controllers.jref.current_app", DummyApp())

    class Session: ...
    params = MultiDict({
        "doi": Meta.doi,
        "journal_ref": Meta.journal_ref,
        "report_num": Meta.report_num,
        "confirmed": "true",   # True → skip confirmation branch
    })

    data, code, headers = jref("POST", params, Session(), submission_id=1)

    assert code == 200
    assert headers == {}
    assert "require_confirmation" not in data
