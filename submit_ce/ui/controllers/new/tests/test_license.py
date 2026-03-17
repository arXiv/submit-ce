"""Tests for :mod:`submit_ce.controllers.license`."""

from submit_ce.domain.submission import Submission
from submit_ce.ui.tests import gets
from submit_ce.ui.tests.csrf_util import parse_csrf_token


def test_license(app, authorized_client, sub_policy):
    sub: Submission = sub_policy
    #assert sub and not sub.license

    url = "/93489292/classification"
    resp = authorized_client.get(url)
    assert resp.status_code == 404

    url = f"/{sub.submission_id}/license"
    resp = authorized_client.get(url)
    assert resp.status_code == 200 and b"<title>Select a License" in resp.data and b"<form " in resp.data

    resp = authorized_client.post(url)
    assert resp.status_code == 400 and b"<title>Select a License" in resp.data and b"<form " in resp.data
    resp = authorized_client.post(url, data={})
    assert resp.status_code == 400 and b"<title>Select a License" in resp.data and b"<form " in resp.data
    resp = authorized_client.post(url, data={'csrf_token':parse_csrf_token(resp)})
    assert resp.status_code == 400 and b"<title>Select a License" in resp.data and b"<form " in resp.data

    license = "http://arxiv.org/licenses/nonexclusive-distrib/1.0/"
    resp = authorized_client.post(url, data={
        'csrf_token':parse_csrf_token(resp),
        'license': license,
        'action': 'next'})
    assert resp.status_code == 303 and resp.headers["Location"] == f"/{sub.submission_id}/classification"
    gets(app,sub).license == license

    resp = authorized_client.get(url)
    resp = authorized_client.post(url, data={
        'csrf_token':parse_csrf_token(resp),
        'license': license,
        'action': 'next'})
    assert resp.status_code == 303 and resp.headers["Location"] == f"/{sub.submission_id}/classification"
    gets(app,sub).license == license
