"""Tests for :mod:`submit_ce.controllers.jref` - test for announced submission."""
import pytest
from werkzeug.datastructures import MultiDict
from submit_ce.domain.agent import InternalClient
from submit_ce.ui.controllers.jref import jref  # jref function

@pytest.mark.usefixtures("app")
def test_jref_get_announced_returns_prepopulated_form(monkeypatch, authorized_user):
    class Meta:
        doi = "10.1/old"
        journal_ref = "Old JR"
        report_num = "RN-1"

    class Sub:
        is_announced = True
        metadata = Meta()

    # Backend + auth patches in the controller namespace
    monkeypatch.setattr(
        "submit_ce.ui.controllers.jref.get_submission",
        lambda sid: (Sub(), [])
    )
    monkeypatch.setattr(
        "submit_ce.ui.controllers.jref.user_and_client_from_session",
        lambda session: (authorized_user, InternalClient(name="test-client"))
    )

    # ❗Disable CSRF on the form class via module path (no need for request/session)
    monkeypatch.setattr(
        "submit_ce.ui.controllers.jref.JREFForm.Meta.csrf",
        False,
        raising=False,
    )

    data, code, _ = jref("GET", MultiDict(), object(), submission_id=42)

    assert code == 200
    assert "form" in data
    form = data["form"]
    assert form.doi.data == "10.1/old"
    assert form.journal_ref.data == "Old JR"
    assert form.report_num.data == "RN-1"
