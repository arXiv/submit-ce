# coding: utf-8
import pytest
from fastapi.testclient import TestClient

from submit_ce.api.domain import Submission


def test_get_service_status(client: TestClient):
    """Test case for get_service_status"""
    headers = {}
    response = client.request("GET", "/v1/status", headers=headers)
    assert response.status_code == 200


def test_start(client: TestClient):
    """Test case for begin."""
    headers = {    }
    response = client.request("POST", "/v1/start", headers=headers,
                              json={"submission_type":"new"})
    assert response.status_code == 200
    sid = response.text
    assert sid is not None
    assert '"' not in sid

    response = client.request("GET", f"/v1/submission/{sid}", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert str(data['submission_id']) == sid


def test_start_alter(client: TestClient):
    response = client.request("POST", "/v1/start", headers={},
                              json={"submission_type":"replacement",
                                    "paperid": "totally_fake_paperid"})
    assert response.status_code == 404


def test_submission_id_accept_policy_post(client: TestClient):
    """Test case for submission_id_accept_policy_post."""
    headers = {}
    response = client.request("POST", "/v1/start", headers=headers,
                              json={"submission_type": "new"})
    assert response.status_code == 200
    sid = response.text
    assert sid is not None
    response = client.request("GET", f"/v1/submission/{sid}", headers=headers)
    assert response.status_code == 200
    submission = Submission.model_validate_json(response.text)
    assert str(submission.submission_id) == sid
    assert submission.is_active

    assert not submission.submitter_accepts_policy
    assert not submission.is_source_processed
    assert not submission.submitter_contact_verified
    assert not submission.is_announced
    assert not submission.is_deleted
    assert not submission.is_finalized
    assert not submission.is_on_hold
    assert not submission.license
    assert not submission.source_content
    assert not submission.primary_classification
    assert not submission.secondary_classification
    assert not submission.submitted

    response = client.request(
        "POST",
        f"/v1/submission/888888/acceptPolicy",
        headers=headers,
        json={"accepted_policy_id": 3})
    assert response.status_code == 404

    response = client.request(
        "POST",
        f"/v1/submission/{sid}/acceptPolicy",
        headers=headers,
        json={"junk_data": 1})
    assert response.status_code >= 422

    response = client.request(
        "POST",
        f"/v1/submission/{sid}/acceptPolicy",
        headers=headers,
        json={"accepted_policy_id": 1})
    assert response.status_code >= 400

    response = client.request(
       "POST",
       f"/v1/submission/{sid}/acceptPolicy",
       headers=headers,
       json={"accepted_policy_id":3})
    assert response.status_code == 200

    response = client.request("GET", f"/v1/submission/{sid}", headers=headers)
    assert response.status_code == 200
    submission = Submission.model_validate_json(response.text)
    assert str(submission.submission_id) == sid
    assert submission.submitter_accepts_policy

    response = client.request(
       "POST",
       f"/v1/submission/{sid}/acceptPolicy",
       headers=headers,
       json={"accepted_policy_id":3})
    assert response.status_code == 200

def test_license(client: TestClient):
    headers = {}
    response = client.request("POST", "/v1/start", headers=headers,
                              json={"submission_type": "new"})
    assert response.status_code == 200
    sid = response.text
    assert sid is not None
    response = client.request("GET", f"/v1/submission/{sid}", headers=headers)
    assert response.status_code == 200 and not response.json()['license']

    response = client.request("POST", f"/v1/submission/{sid}/setLicense",
        json={"license_uri":"http://arxiv.org/licenses/nonexclusive-distrib/1.0/"},
                              headers=headers)
    assert response.status_code == 200

    response = client.request("GET", f"/v1/submission/{sid}", headers=headers)
    assert response.status_code == 200
    submission = Submission.model_validate_json(response.text)
    assert str(submission.submission_id) == sid
    assert submission.license is not None and submission.license.uri  == "http://arxiv.org/licenses/nonexclusive-distrib/1.0/"

    response = client.request("POST", f"/v1/submission/{sid}/setLicense",
        json={"license_uri":"bogus_license"},
                              headers=headers)
    assert response.status_code == 422

    no_longer_valid = "http://arxiv.org/licenses/assumed-1991-2003/"
    response = client.request("POST", f"/v1/submission/{sid}/setLicense",
        json={"license_uri":no_longer_valid}, headers=headers)
    assert response.status_code == 422

@pytest.mark.parametrize("invalid_license",[
    "http://arxiv.org/licenses/assumed-1991-2003/",
    "http://creativecommons.org/licenses/by/3.0/",
    "http://creativecommons.org/licenses/by-nc-sa/3.0/",
    "http://creativecommons.org/licenses/publicdomain/"
    "http://creativecommons.org/licenses/fake_not_reall/",
    "",
    "totally_fake_not_reall",
])
def test_invalid_license(client: TestClient, invalid_license:str):
    headers = {}
    response = client.request("POST", "/v1/start", headers=headers,
                              json={"submission_type": "new"})
    assert response.status_code == 200
    sid = response.text
    assert sid is not None

    no_longer_valid = "http://arxiv.org/licenses/assumed-1991-2003/"
    response = client.request("POST", f"/v1/submission/{sid}/setLicense",
                              json={"license_uri": invalid_license}, headers=headers)
    assert response.status_code == 422

def test_basic_submission(client: TestClient):
    headers={}
    response = client.request("POST", "/v1/start", headers=headers,
                              json={"submission_type": "new"})
    assert response.status_code == 200
    sid = response.text
    assert sid is not None and '"' not in sid

    response = client.request(
       "POST",
       f"/v1/submission/{sid}/acceptPolicy",
       headers=headers,
       json={"accepted_policy_id":3})
    assert response.status_code == 200

    response = client.request("POST", f"/v1/submission/{sid}/setLicense",
                              json={"license_uri": "http://arxiv.org/licenses/nonexclusive-distrib/1.0/"},
                              headers=headers)
    assert response.status_code == 200

    response = client.request("POST", f"/v1/submission/{sid}/assertAuthorship",
                              json={"i_am_author": True},
                              headers=headers)
    assert response.status_code == 200

    response = client.request("POST", f"/v1/submission/{sid}/setCategories",
                              json={"primary_category": "astro-ph.EP", "secondary_categories": ["astro-ph.GA"]},
                              headers=headers)
    assert response.status_code == 200 or response.content == ""

    response = client.request("POST", f"/v1/submission/{sid}/setCategories",
                              json={"primary_category": "astro-ph.EP", "secondary_categories": []},
                              headers=headers)
    assert response.status_code == 200 or response.content == ""

    response = client.request("POST", f"/v1/submission/{sid}/setMetadata",
                              json={
                                  "title": "fake title that should be good enough",
                                  "abstract": "fake abstract that should be good enough",
                                  "authors": "Smith, Bob",
                                  "comments": "totally good"
                                  },
                              headers=headers)
    assert response.status_code == 200

    response = client.request("POST", f"/v1/submission/{sid}/setMetadata",
                        json={
                            "msc_class": "bogus class",
                            "acm_class": "2.34",
                            "report_num": "24333",
                            "doi": "totally_fake_doi",
                            "journal_ref": "also totally fake jref",
                        },
                          headers=headers)

    assert response.status_code == 200 or response.text == ""

