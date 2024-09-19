# coding: utf-8
import pytest
from fastapi.testclient import TestClient

from submit_ce.submit_fastapi.api.models.events import AgreedToPolicy


def test_get_service_status(client: TestClient):
    """Test case for get_service_status"""
    headers = {}
    response = client.request("GET", "/v1/status", headers=headers)
    assert response.status_code == 200


def test_get_submission(client: TestClient):
    """Test case for get_submission

    
    """

    headers = {
    }
    # uncomment below to make a request
    #response = client.request(
    #    "GET",
    #    "/{submission_id}".format(submission_id='submission_id_example'),
    #    headers=headers,
    #)

    # uncomment below to assert the status code of the HTTP response
    #assert response.status_code == 200


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
    data = response.json()
    assert str(data['submission_id']) == sid
    assert data['agreement_id'] != 3
    assert data['agree_policy'] == 0

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
    data = response.json()
    assert str(data['submission_id']) == sid
    assert data['agreement_id'] == 3
    assert data['agree_policy'] == 1

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
    assert (response.status_code == 200
            and response.json()['license'] == "http://arxiv.org/licenses/nonexclusive-distrib/1.0/")

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


def test_submission_id_deposit_packet_packet_format_get(client: TestClient):
    """Test case for submission_id_deposit_packet_packet_format_get

    
    """

    headers = {
    }
    # uncomment below to make a request
    #response = client.request(
    #    "GET",
    #    "/{submission_id}/deposit_packet/{packet_format}".format(submission_id='submission_id_example', packet_format='packet_format_example'),
    #    headers=headers,
    #)

    # uncomment below to assert the status code of the HTTP response
    #assert response.status_code == 200


def test_submission_id_deposited_post(client: TestClient):
    """Test case for submission_id_deposited_post

    
    """

    headers = {
    }
    # uncomment below to make a request
    #response = client.request(
    #    "POST",
    #    "/{submission_id}/Deposited".format(submission_id='submission_id_example'),
    #    headers=headers,
    #)

    # uncomment below to assert the status code of the HTTP response
    #assert response.status_code == 200


def test_submission_id_mark_processing_for_deposit_post(client: TestClient):
    """Test case for submission_id_mark_processing_for_deposit_post

    
    """

    headers = {
    }
    # uncomment below to make a request
    #response = client.request(
    #    "POST",
    #    "/{submission_id}/markProcessingForDeposit".format(submission_id='submission_id_example'),
    #    headers=headers,
    #)

    # uncomment below to assert the status code of the HTTP response
    #assert response.status_code == 200


def test_submission_id_unmark_processing_for_deposit_post(client: TestClient):
    """Test case for submission_id_unmark_processing_for_deposit_post

    
    """

    headers = {
    }
    # uncomment below to make a request
    #response = client.request(
    #    "POST",
    #    "/{submission_id}/unmarkProcessingForDeposit".format(submission_id='submission_id_example'),
    #    headers=headers,
    #)

    # uncomment below to assert the status code of the HTTP response
    #assert response.status_code == 200

