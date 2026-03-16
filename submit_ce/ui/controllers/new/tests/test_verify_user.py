"""Tests for :mod:`submit_ce.controllers.verify_user`."""

from submit_ce.api.domain.submission import Submission
from submit_ce.ui.tests import gets
from submit_ce.ui.tests.csrf_util import parse_csrf_token
from http import HTTPStatus as status

def test_verify_no_sub(app, authorized_client):
    url = "/93489292/policy"
    resp = authorized_client.get(url)
    assert resp.status_code == status.NOT_FOUND

def test_verify(app, authorized_client, sub_created):
    sub: Submission = sub_created
    assert sub and not sub.submitter_contact_verified
    def sub_from_db():
        return gets(app, sub)

    url = f"/{sub.submission_id}/verify_user"
    resp = authorized_client.get(url)
    assert resp.status_code == status.OK and \
        b"<title>Verify User" in resp.data \
        and b"<form " in resp.data

    resp = authorized_client.post(url, data={"csrf_token":parse_csrf_token(resp),
                                             "verify_user": "false"})
    assert resp.status_code == 400

    resp = authorized_client.post(url, data={"csrf_token":parse_csrf_token(resp),
                                             "verify_user": "true",
                                             "action":"next"})
    assert resp.status_code == 303 and \
        resp.headers["Location"] == f"/{sub.submission_id}/policy"
