"""Tests for :mod:`submit_ce.controllers.policy`."""

from submit_ce.api.domain.submission import Submission
from submit_ce.ui.tests import gets
from submit_ce.ui.tests.csrf_util import parse_csrf_token
from http import HTTPStatus as status

def test_policy(app, authorized_client, sub_license):
    sub: Submission = sub_license
    assert sub and not sub.submitter_accepts_policy
    current_policy_id = 3
    def sub_from_db():
        return gets(app, sub)
    
    url = "/93489292/policy"
    resp = authorized_client.get(url)
    assert resp.status_code == status.NOT_FOUND

    url = f"/{sub.submission_id}/policy"
    resp = authorized_client.get(url)
    assert resp.status_code == status.OK and \
        b"<title>Acknowledge Policy Statement" in resp.data \
        and b"<form " in resp.data

    resp = authorized_client.post(url, data={})  # tests no data
    assert resp.status_code == status.BAD_REQUEST and \
        b"<title>Acknowledge Policy Statement" in resp.data \
        and not sub_from_db().submitter_accepts_policy

    resp = authorized_client.post(url, data={"csrf_token": parse_csrf_token(resp)})  # tests no data
    assert resp.status_code == status.BAD_REQUEST and \
        b"<title>Acknowledge Policy Statement" in resp.data \
        and not sub_from_db().submitter_accepts_policy

    # test no policy_id
    resp = authorized_client.post(url, data={"csrf_token": parse_csrf_token(resp),
                                             "policy": "y"})
    assert resp.status_code == status.BAD_REQUEST and \
        b"<title>Acknowledge Policy Statement" in resp.data \
        and not sub_from_db().submitter_accepts_policy
    
    # test no policy
    resp = authorized_client.post(url, data={"csrf_token": parse_csrf_token(resp),
                                             "policy_id": current_policy_id})
    assert resp.status_code == status.BAD_REQUEST \
        and not sub_from_db().submitter_accepts_policy
    
    # test crazy additional data
    resp = authorized_client.post(url, data={"csrf_token": parse_csrf_token(resp),
                                             "policy": "y",
                                             "policy_id": current_policy_id,
                                             "x": "I DON'T AGREE TO THIS POLICY"})
    assert resp.status_code == status.BAD_REQUEST \
        and not sub_from_db().submitter_accepts_policy

    # test unexpected policy_id
    resp = authorized_client.post(url, data={"csrf_token": parse_csrf_token(resp),
                                             "policy_id": "3RA1N1AC",
                                             "policy": "y"})
    assert resp.status_code == status.BAD_REQUEST \
        and not sub_from_db().submitter_accepts_policy

    resp = authorized_client.post(url, data={"csrf_token": parse_csrf_token(resp),
                                             "policy_id": f"{current_policy_id}-RA1N1AC",
                                             "policy": "y"})
    assert resp.status_code == status.BAD_REQUEST \
        and not sub_from_db().submitter_accepts_policy

    # test unexpected policy
    resp = authorized_client.post(url, data={"csrf_token": parse_csrf_token(resp),
                                             "policy_id": current_policy_id,
                                             "policy": "3RA1N1AC"})
    assert resp.status_code == status.BAD_REQUEST \
        and not sub_from_db().submitter_accepts_policy

    # test good policy
    assert not sub_from_db().submitter_accepts_policy
    resp = authorized_client.post(url, data={"csrf_token": parse_csrf_token(resp),
                                             "policy_id": current_policy_id,
                                             "policy": "y"})
    assert resp.status_code == status.OK and sub_from_db().submitter_accepts_policy

    # attempt repost 
    resp = authorized_client.post(url, data={"csrf_token": parse_csrf_token(resp),
                                             "policy_id": current_policy_id,
                                             "policy": "y"})
    assert resp.status_code == status.OK and sub_from_db().submitter_accepts_policy

    # attempt repost but reject
    resp = authorized_client.post(url, data={"csrf_token": parse_csrf_token(resp),
                                             "policy_id": current_policy_id,
                                             "policy": "false"})
    assert resp.status_code == status.BAD_REQUEST and sub_from_db().submitter_accepts_policy
    resp = authorized_client.post(url, data={"csrf_token": parse_csrf_token(resp),
                                             "policy_id": current_policy_id,
                                             "policy": "n"})
    assert resp.status_code == status.BAD_REQUEST and sub_from_db().submitter_accepts_policy
    resp = authorized_client.post(url, data={"csrf_token": parse_csrf_token(resp),
                                             "policy_id": current_policy_id,
                                             "policy": "0"})
    assert resp.status_code == status.BAD_REQUEST and sub_from_db().submitter_accepts_policy
    resp = authorized_client.post(url, data={"csrf_token": parse_csrf_token(resp),
                                             "policy_id": current_policy_id,
                                             "policy": 0})
    assert resp.status_code == status.BAD_REQUEST and sub_from_db().submitter_accepts_policy
