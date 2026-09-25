"""Endpoint dispatch + auth tests for the mutation API (SUBMISSION-257, no DB)."""
import os

os.environ.setdefault("STORE", "null")
os.environ.setdefault("EMAIL_MODE", "TESTING")
os.environ.setdefault("LOCAL_LOGIN", "1")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from submit_ce.fastapi.app import create_api_app  # noqa: E402
from submit_ce.fastapi.auth import get_user_and_client  # noqa: E402
from submit_ce.domain.event import (  # noqa: E402
    AdminRemove, UnRemove, CreateSubmissionVersion,
)
from submit_ce.domain.agent import PublicUser, HttpClient  # noqa: E402


class _StubApi:
    """Records the events passed to save() instead of touching a DB."""

    def __init__(self):
        self.saved = []

    def save(self, *events, submission_id=None):
        self.saved.append((events, submission_id))
        return ({"submission_id": submission_id}, list(events))

    def get(self, submission_id):
        return {"submission_id": submission_id}


def _app_with_stub():
    app = create_api_app()
    app.state.api = _StubApi()
    app.dependency_overrides[get_user_and_client] = lambda: (
        PublicUser(user_id="1", name="Tester", email="t@example.org"),
        HttpClient(remote_addr="1.2.3.4"),
    )
    return app, app.state.api


@pytest.mark.parametrize("path,event_cls,code", [
    ("/submission/123/resubmit", CreateSubmissionVersion, 201),
    ("/submission/123/remove", AdminRemove, 200),
    ("/submission/123/unremove", UnRemove, 200),
])
def test_endpoint_dispatches_event(path, event_cls, code):
    app, stub = _app_with_stub()
    resp = TestClient(app).post(path)
    assert resp.status_code == code
    events, sid = stub.saved[-1]
    assert isinstance(events[0], event_cls)
    assert sid == "123"


@pytest.mark.parametrize("path", [
    "/submission/123/resubmit",
    "/submission/123/remove",
    "/submission/123/unremove",
])
def test_endpoint_requires_auth(path):
    resp = TestClient(create_api_app()).post(path)
    assert resp.status_code == 401


@pytest.mark.parametrize("path,event_cls", [
    ("/submission/123/remove", AdminRemove),
    ("/submission/123/unremove", UnRemove),
])
def test_endpoint_passes_comment_to_event(path, event_cls):
    app, stub = _app_with_stub()
    resp = TestClient(app).post(path, json={"comment": "because reasons"})
    assert resp.status_code == 200
    events, _sid = stub.saved[-1]
    assert isinstance(events[0], event_cls)
    assert events[0].comment == "because reasons"
