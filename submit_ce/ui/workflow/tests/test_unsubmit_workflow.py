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


def test_unsubmit_submission(app, authorized_user_session, authorized_client, authorized_user):
    """Test that progress through the unsubmit workflow."""

    session, jwt = authorized_user_session
    client = authorized_client
    user = authorized_user
    ua = InternalClient(name=f"test_client_{__file__}")

    # Create a finalized submission.
    ua = InternalClient(name=f"test_client_{__file__}")
    cc0 = 'http://creativecommons.org/publicdomain/zero/1.0/'
    submission, _ = api.save(
        CreateSubmission(creator=user, client=ua),
        ConfirmContactInformation(creator=user, client=ua),
        ConfirmAuthorship(creator=user, client=ua, submitter_is_author=True),
        SetLicense(
            creator=user, client=ua,
            license_uri=cc0,
            license_name='CC0 1.0'
        ),
        ConfirmPolicy(creator=user, client=ua),
        SetPrimaryClassification(creator=user, client=ua,
                                 category='astro-ph.GA'),
        SetUploadPackage(
            creator=user, client=ua,
            checksum="a9s9k342900skks03330029k",
            source_format=SubmissionContent.Format.TEX,
            identifier="123",
            uncompressed_size=593992,
            compressed_size=59392,
        ),
        SetTitle(creator=user, client=ua, title='foo title'),
        SetAbstract(creator=user, client=ua, abstract='ab stract' * 20),
        SetComments(creator=user, client=ua, comments='indeed'),
        SetReportNumber(creator=user, client=ua, report_num='the number 12'),
        SetAuthors(
            creator=user, client=ua,
            authors=[Author(
                order=0,
                forename='Bob',
                surname='Paulson',
                email='Robert.Paulson@nowhere.edu',
                affiliation='Fight Club'
            )]
        ),
        FinalizeSubmission(creator=user, client=ua)
    )

    submission_id = submission.submission_id

    # Get the unsubmit confirmation page.
    endpoint = f'/{submission_id}/unsubmit'
    response = client.get(endpoint)
    assert response.status_code == status.OK and response.content_type == 'text/html; charset=utf-8'
    assert 'Unsubmit This Submission' in response.text
    token = _parse_csrf_token(response)

    # Confirm the submission should be unsubmitted
    request_data = {'confirmed': True, 'csrf_token': token}
    response = client.post(endpoint, data=request_data)
    assert response.status_code == status.SEE_OTHER

    # Check what happened.
    submission = api.get(submission_id=str(submission_id))
    assert submission.status == 0 or submission.status == "working"
