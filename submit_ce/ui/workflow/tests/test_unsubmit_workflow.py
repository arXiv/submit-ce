"""Tests for the submission application as a whole."""

import os
import tempfile
from http import HTTPStatus as status
from unittest import TestCase, mock
from urllib.parse import urlparse

from arxiv.auth.auth import scopes
from arxiv.auth.helpers import generate_token

from submit_ce.api.domain import Author, SubmissionContent
from submit_ce.api.domain import User
from submit_ce.api.domain.agent import InternalClient
from submit_ce.api.domain.event import SetPrimaryClassification, CreateSubmission, ConfirmContactInformation, \
    ConfirmAuthorship, SetLicense, ConfirmPolicy, SetUploadPackage, SetTitle, SetAbstract, SetComments, SetReportNumber, \
    SetAuthors, FinalizeSubmission
from submit_ce.ui.backend import api
from submit_ce.ui.tests import CtrlBase
from submit_ce.ui.tests.csrf_util import parse_csrf_token


def _parse_csrf_token( response):
    try:
        return parse_csrf_token(response)
    except AttributeError:
        assert 0, 'Could not find CSRF token'


def test_unsubmit_submission(authorized_client, submitted_submission):
    """Test that progress through the unsubmit workflow."""

    client = authorized_client
    submission = submitted_submission

    # Get the unsubmit confirmation page.
    endpoint = f'/{submission.submission_id}/unsubmit'
    response = client.get(endpoint)
    assert response.status_code == status.OK and response.content_type == 'text/html; charset=utf-8'
    assert 'Unsubmit This Submission' in response.text
    token = _parse_csrf_token(response)

    # Confirm the submission should be unsubmitted
    request_data = {'confirmed': True, 'csrf_token': token}
    response = client.post(endpoint, data=request_data)
    assert response.status_code == status.SEE_OTHER

    # Check what happened.
    submission = api.get(submission_id=str(submission.submission_id))
    assert submission.status == 0 or submission.status == "working"
