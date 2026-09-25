"""Wiring/smoke tests for the submission mutation API (no DB required)."""
import os

os.environ.setdefault("STORE", "null")
os.environ.setdefault("EMAIL_MODE", "TESTING")
os.environ.setdefault("LOCAL_LOGIN", "1")

from fastapi.testclient import TestClient  # noqa: E402

from submit_ce.fastapi.app import create_api_app  # noqa: E402


def test_status_ok():
    client = TestClient(create_api_app())
    resp = client.get("/status")
    assert resp.status_code == 200
    assert resp.text == "ok"


def test_routes_registered():
    paths = {r.path for r in create_api_app().routes}
    assert "/submission/{submission_id}" in paths
    assert "/submission/{submission_id}/with_history" in paths
    assert "/submission/{submission_id}/resubmit" in paths


def test_resubmit_requires_auth():
    client = TestClient(create_api_app())
    resp = client.post("/submission/1234567/resubmit")
    assert resp.status_code == 401
