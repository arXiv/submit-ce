"""Tests for :mod:`submit_ce.controllers.authorship`."""

from http import HTTPStatus as status

from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError, NotFound
from wtforms import Form

import submit_ce as events
from submit_ce.api.domain.event import ConfirmAuthorship
from submit_ce.ui.controllers.new import authorship
from submit_ce.ui.tests.csrf_util import parse_csrf_token

def get(appx, subx):
    with appx.app_context():
        return appx.api.get(subx.submission_id)

def test_authorship_form(app, authorized_client, sub_verified_user):
    sub = sub_verified_user
    assert sub and not sub.submitter_is_author

    url = f"/{sub.submission_id}/authorship"
    resp = authorized_client.get(url)
    assert resp.status_code == 200 and b"Confirm Authorship" in resp.data and b"<form " in resp.data

    resp = authorized_client.post(url, data={})
    assert resp.status_code == 400 and b"<title>Confirm Authorship" in resp.data and b"is-danger" in resp.data
    assert not get(app, sub).submitter_is_author
    resp = authorized_client.post(url, data={'action':'next','csrf_token':parse_csrf_token(resp)})
    assert resp.status_code == 400 and b"<title>Confirm Authorship" in resp.data and b"is-danger" in resp.data
    assert not get(app, sub).submitter_is_author
    resp = authorized_client.post(url, data={'action':'next','csrf_token':parse_csrf_token(resp), 'authorship': 'n'})
    assert resp.status_code == 400 and b"<title>Confirm Authorship" in resp.data and b"is-danger" in resp.data
    assert not get(app, sub).submitter_is_author
    resp = authorized_client.post(url, data={'action':'next','csrf_token':parse_csrf_token(resp), 'authorship': 'bad_value'})
    assert resp.status_code == 400 and b"<title>Confirm Authorship" in resp.data and b"is-danger" in resp.data
    assert not get(app, sub).submitter_is_author
    resp = authorized_client.post(url, data={'action':'next','csrf_token':parse_csrf_token(resp), 'authorship': ''})
    assert resp.status_code == 400 and b"<title>Confirm Authorship" in resp.data and b"is-danger" in resp.data
    assert not get(app, sub).submitter_is_author

    resp = authorized_client.post(url, data={'action':'next','csrf_token':parse_csrf_token(resp), 'authorship': 'y'})
    assert resp.status_code == 303 and resp.headers["Location"] == f"/{sub.submission_id}/license"
    assert get(app, sub).submitter_is_author


def test_no_submission(app, authorized_client):
    url = f"/2343/authorship"
    resp = authorized_client.get(url)
    assert resp.status_code == 404

    url = f"/totaljunkid/authorship"
    resp = authorized_client.get(url)
    assert resp.status_code == 404
