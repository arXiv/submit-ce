"""Tests for :mod:`submit_ce.controllers.jref` - test unannounced redirect to create."""
import pytest
from werkzeug.datastructures import MultiDict
from submit_ce.ui.controllers.jref import jref

@pytest.mark.usefixtures("app")
def test_jref_get_unannounced_redirects(monkeypatch):
    """
    If the submission is not announced, GET should flash a failure and
    redirect (303) back to the create_submission page.
    """

    class Sub:
        is_announced = False
        metadata = None

    # Patch the controller's bindings to avoid backend and Flask context
    monkeypatch.setattr(
        "submit_ce.ui.controllers.jref.get_submission",
        lambda sid: (Sub(), [])
    )
    monkeypatch.setattr(
        "submit_ce.ui.controllers.jref.user_and_client_from_session",
        lambda session: ("creator", "client")
    )
    # Avoid needing request/session context for flash + url_for
    monkeypatch.setattr(
        "submit_ce.ui.controllers.jref.alerts.flash_failure",
        lambda *a, **k: None
    )
    monkeypatch.setattr(
        "submit_ce.ui.controllers.jref.url_for",
        lambda endpoint, **kwargs: "/create"
    )

    class Session: ...
    data, code, headers = jref(
        method="GET",
        params=MultiDict(),
        session=Session(),
        submission_id=1234
    )

    assert code == 303
    assert headers.get("Location") == "/create"