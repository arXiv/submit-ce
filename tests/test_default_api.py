# coding: utf-8

from fastapi.testclient import TestClient


from arxiv.submit_fastapi.models.agreement import Agreement  # noqa: F401


def test_get_service_status(client: TestClient):
    """Test case for get_service_status

    
    """

    headers = {
    }
    # uncomment below to make a request
    #response = client.request(
    #    "GET",
    #    "/status",
    #    headers=headers,
    #)

    # uncomment below to assert the status code of the HTTP response
    #assert response.status_code == 200


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


def test_new(client: TestClient):
    """Test case for new

    
    """

    headers = {
    }
    # uncomment below to make a request
    #response = client.request(
    #    "POST",
    #    "/",
    #    headers=headers,
    #)

    # uncomment below to assert the status code of the HTTP response
    #assert response.status_code == 200


def test_submission_id_accept_policy_post(client: TestClient):
    """Test case for submission_id_accept_policy_post

    
    """
    agreement = {"submission_id":"submission_id","agreement":"agreement","name":"name"}

    headers = {
    }
    # uncomment below to make a request
    #response = client.request(
    #    "POST",
    #    "/{submission_id}/acceptPolicy".format(submission_id='submission_id_example'),
    #    headers=headers,
    #    json=agreement,
    #)

    # uncomment below to assert the status code of the HTTP response
    #assert response.status_code == 200


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

