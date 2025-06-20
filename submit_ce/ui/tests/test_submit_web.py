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


# TODO: finish building out this test suite. The current tests run up to
# file upload. Once the remaining stages have stabilized, this should have
# tests for the whole submit process.


class TestSubmissionWorkflow(CtrlBase):
    """Tests that progress through the submission workflow in various ways."""
    def _parse_csrf_token(self, response):
        try:
            return parse_csrf_token(response)
        except AttributeError:
            self.fail('Could not find CSRF token')

    def test_create_submission(self):
        """User creates a new submission, and proceeds up to upload stage."""
        # Get the submission creation page.
        response = self.client.get('/')
        self.assertEqual(status.OK, response.status_code)
        self.assertEqual(response.content_type, 'text/html; charset=utf-8')
        token = self._parse_csrf_token(response)

        # Create a submission.
        response = self.client.post('/',
                                    data={'new': 'new',
                                          'csrf_token': token})
        self.assertEqual(response.status_code, status.SEE_OTHER)

        # Get the next page in the process. This should be the verify_user stage.
        next_page = urlparse(response.headers['Location'])
        self.assertIn('verify_user', next_page.path)
        response = self.client.get(next_page.path)
        self.assertIn(b'By checking this box, I verify that my user information is correct.',
                      response.data)
        token = self._parse_csrf_token(response)
        upload_id, _ = next_page.path.lstrip('/').split('/verify_user', 1)

        # Make sure that the user cannot skip forward to subsequent steps.
        response = self.client.get(f'/{upload_id}/file_upload')
        self.assertEqual(response.status_code, status.FOUND)

        response = self.client.get(f'/{upload_id}/final_preview')
        self.assertEqual(response.status_code, status.FOUND)

        response = self.client.get(f'/{upload_id}/add_optional_metadata')
        self.assertEqual(response.status_code, status.FOUND)

        # Submit the verify user page.
        response = self.client.post(next_page.path,
                                    data={'verify_user': 'y',
                                          'action': 'next',
                                          'csrf_token': token},
                                    headers=self.headers)
        self.assertEqual(response.status_code, status.SEE_OTHER)

        # Get the next page in the process. This is the authorship stage.
        next_page = urlparse(response.headers['Location'])
        self.assertIn('authorship', next_page.path)
        response = self.client.get(next_page.path)
        self.assertIn(b'I am an author of this paper', response.data)
        token = self._parse_csrf_token(response)

        # Submit the authorship page.
        response = self.client.post(next_page.path,
                                    data={'authorship': 'y',
                                          'action': 'next',
                                          'csrf_token': token},
                                    headers=self.headers)
        self.assertEqual(response.status_code, status.SEE_OTHER)

        # Get the next page in the process. This is the license stage.
        next_page = urlparse(response.headers['Location'])
        self.assertIn('license', next_page.path)
        response = self.client.get(next_page.path)
        self.assertIn(b'Select a License', response.data)
        token = self._parse_csrf_token(response)

        # Submit the license page.
        selected = "http://creativecommons.org/licenses/by-sa/4.0/"
        response = self.client.post(next_page.path,
                                    data={'license': selected,
                                          'action': 'next',
                                          'csrf_token': token},
                                    headers=self.headers)
        self.assertEqual(response.status_code, status.SEE_OTHER)

        # Get the next page in the process. This is the policy stage.
        next_page = urlparse(response.headers['Location'])
        self.assertIn('policy', next_page.path)
        response = self.client.get(next_page.path)
        self.assertIn(
            b'By checking this box, I agree to the policies listed on'
            b' this page',
            response.data
        )
        token = self._parse_csrf_token(response)

        # Submit the policy page.
        response = self.client.post(next_page.path,
                                    data={'policy': 'y',
                                          'action': 'next',
                                          'csrf_token': token},
                                    headers=self.headers)
        self.assertEqual(response.status_code, status.SEE_OTHER)

        # Get the next page in the process. This is the primary category stage.
        next_page = urlparse(response.headers['Location'])
        self.assertIn('classification', next_page.path)
        response = self.client.get(next_page.path)
        self.assertIn(b'Choose a Primary Classification', response.data)
        token = self._parse_csrf_token(response)

        # Submit the primary category page.
        response = self.client.post(next_page.path,
                                    data={'category': 'astro-ph.GA',
                                          'action': 'next',
                                          'csrf_token': token},
                                    headers=self.headers)
        self.assertEqual(response.status_code, status.SEE_OTHER)

        # Get the next page in the process. This is the cross list stage.
        next_page = urlparse(response.headers['Location'])
        self.assertIn('cross', next_page.path)
        response = self.client.get(next_page.path)
        self.assertIn(b'Choose Cross-List Classifications', response.data)
        token = self._parse_csrf_token(response)

        # Submit the cross-list category page.
        response = self.client.post(next_page.path,
                                    data={'category': 'astro-ph.CO',
                                          'csrf_token': token},
                                    headers=self.headers)
        self.assertEqual(response.status_code, status.OK)

        response = self.client.post(next_page.path,
                                    data={'action': 'next'},
                                    headers=self.headers)
        self.assertEqual(response.status_code, status.SEE_OTHER)

        # Get the next page in the process. This is the file upload stage.
        next_page = urlparse(response.headers['Location'])
        self.assertIn('upload', next_page.path)
        response = self.client.get(next_page.path)
        self.assertIn(b'Upload Files', response.data)
        token = self._parse_csrf_token(response)

