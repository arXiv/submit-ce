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
from submit_ce.api.domain.event import SetPrimaryClassification, CreateSubmission, ConfirmContactInformation, \
    ConfirmAuthorship, SetLicense, ConfirmPolicy, SetUploadPackage, SetTitle, SetAbstract, SetComments, SetReportNumber, \
    SetAuthors, FinalizeSubmission
from submit_ce.ui.backend import api
from submit_ce.ui.tests import CtrlBase
from submit_ce.ui.tests.csrf_util import parse_csrf_token

class TestUnsubmitWorkflow(CtrlBase):
    """Tests that progress through the unsubmit workflow."""

    def setUp(self):
        """Create an application instance."""
        self.app = create_ui_web_app()
        os.environ['JWT_SECRET'] = str(self.app.config.get('JWT_SECRET', 'fo'))
        _, self.db = tempfile.mkstemp(suffix='.db')
        self.app.config['CLASSIC_DATABASE_URI'] = f'sqlite:///{self.db}'
        self.user = User('1234', 'foo@bar.com', endorsements=['astro-ph.GA'])
        self.token = generate_token('1234', 'foo@bar.com', 'foouser',
                                    scope=[scopes.CREATE_SUBMISSION,
                                           scopes.EDIT_SUBMISSION,
                                           scopes.VIEW_SUBMISSION,
                                           scopes.READ_UPLOAD,
                                           scopes.WRITE_UPLOAD,
                                           scopes.DELETE_UPLOAD_FILE],
                                    endorsements=[
                                        'astro-ph.GA',
                                        'astro-ph.CO',
                                    ])
        self.headers = {'Authorization': self.token}
        self.client = self.app.test_client()

        # Create a finalized submission.
        with self.app.app_context():
            classic.create_all()
            session = classic.current_session()

            cc0 = 'http://creativecommons.org/publicdomain/zero/1.0/'
            self.submission, _ = api.save(
                CreateSubmission(creator=self.user),
                ConfirmContactInformation(creator=self.user),
                ConfirmAuthorship(creator=self.user, submitter_is_author=True),
                SetLicense(
                    creator=self.user,
                    license_uri=cc0,
                    license_name='CC0 1.0'
                ),
                ConfirmPolicy(creator=self.user),
                SetPrimaryClassification(creator=self.user,
                                         category='astro-ph.GA'),
                SetUploadPackage(
                    creator=self.user,
                    checksum="a9s9k342900skks03330029k",
                    source_format=SubmissionContent.Format.TEX,
                    identifier=123,
                    uncompressed_size=593992,
                    compressed_size=59392,
                ),
                SetTitle(creator=self.user, title='foo title'),
                SetAbstract(creator=self.user, abstract='ab stract' * 20),
                SetComments(creator=self.user, comments='indeed'),
                SetReportNumber(creator=self.user, report_num='the number 12'),
                SetAuthors(
                    creator=self.user,
                    authors=[Author(
                        order=0,
                        forename='Bob',
                        surname='Paulson',
                        email='Robert.Paulson@nowhere.edu',
                        affiliation='Fight Club'
                    )]
                ),
                FinalizeSubmission(creator=self.user)
            )

        self.submission_id = self.submission.submission_id

    def tearDown(self):
        """Remove the temporary database."""
        os.remove(self.db)

    def _parse_csrf_token(self, response):
        try:
            return parse_csrf_token(response)
        except AttributeError:
            self.fail('Could not find CSRF token')
        return token

    def test_unsubmit_submission(self):
        """User unsubmits a submission."""
        # Get the unsubmit confirmation page.
        endpoint = f'/{self.submission_id}/unsubmit'
        response = self.client.get(endpoint)
        self.assertEqual(response.status_code, status.OK)
        self.assertEqual(response.content_type, 'text/html; charset=utf-8')
        self.assertIn(b'Unsubmit This Submission', response.data)
        token = self._parse_csrf_token(response)

        # Confirm the submission should be unsubmitted
        request_data = {'confirmed': True, 'csrf_token': token}
        response = self.client.post(endpoint, data=request_data,
                                    headers=self.headers)
        self.assertEqual(response.status_code, status.SEE_OTHER)

        with self.app.app_context():
            session = classic.current_session()
            # What happened.
            db_submission = session.query(classic.models.Submission) \
                .filter(classic.models.Submission.submission_id ==
                        self.submission_id).first()
            self.assertEqual(db_submission.status,
                             classic.models.Submission.NOT_SUBMITTED, "")
