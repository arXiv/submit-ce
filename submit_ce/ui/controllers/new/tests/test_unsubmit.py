"""Tests for :mod:`submit_ce.controllers.unsubmit`."""
import pytest
from submit_ce.domain.submission import Submission
from submit_ce.ui.tests.csrf_util import parse_csrf_token


def test_unsubmit_no_sub(authorized_client):
    url = "/93489292/unsubmit"
    resp = authorized_client.get(url)
    assert resp.status_code == 404

@pytest.mark.skip(reason="source_format not yet persisted")
def test_disallow_alter_unsubmit(authorized_client, sub_finalized):
    sub: Submission = sub_finalized
    url = f"/{sub.submission_id}/add_metadata"
    resp = authorized_client.get(url)
    assert resp.status_code == 303 and resp.headers["Location"].endswith("confirmation")

@pytest.mark.skip(reason="source_format not yet persisted")
def test_unsubmit(authorized_client, sub_finalized):
    sub: Submission = sub_finalized
    url = f"/{sub.submission_id}/unsubmit"
    resp = authorized_client.get(url)
    assert resp.status_code == 200
    respx = authorized_client.post(url,data={'confirmed':'true', 'csrf_token':parse_csrf_token(resp)})
    assert respx.status_code == 303 and respx.headers["Location"] == "/"

    url = f"/{sub.submission_id}/unsubmit"
    assert authorized_client.get(url).status_code == 400
    resp = authorized_client.post(url,data={'confirmed':'true', 'csrf_token':parse_csrf_token(resp)})
    assert resp.status_code == 400
