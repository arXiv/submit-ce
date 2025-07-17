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

from submit_ce.ui.tests import CtrlBase
from submit_ce.ui.tests.csrf_util import parse_csrf_token

# SKIP: endorsement doesn't currently work correct due to
# TODO fix submit_ci/ui/auth.py for auth, auth use to be on JWT but will not be in the future
# class TestEndorsementMessaging(CtrlBase):
#     """Verify submitter is shown appropriate messaging about endoresement."""
#     def _parse_csrf_token(self, response):
#         try:
#             return parse_csrf_token(response)
#         except AttributeError:
#             self.fail('Could not find CSRF token')

#     def test_no_endorsements(self):
#         """User is not endorsed (auto or otherwise) for anything."""
#         self.token = generate_token('1234', 'foo@bar.com', 'foouser',
#                                     scope=[scopes.CREATE_SUBMISSION,
#                                            scopes.EDIT_SUBMISSION,
#                                            scopes.VIEW_SUBMISSION,
#                                            scopes.READ_UPLOAD,
#                                            scopes.WRITE_UPLOAD,
#                                            scopes.DELETE_UPLOAD_FILE],
#                                     endorsements=[])
#         self.headers = {'Authorization': self.token}

#         # Get the submission creation page.
#         response = self.client.get('/')
#         self.assertEqual(response.status_code, status.OK)
#         self.assertEqual(response.content_type, 'text/html; charset=utf-8')
#         token = self._parse_csrf_token(response)

#         # Create a submission.
#         response = self.client.post('/',
#                                     data={'new': 'new',
#                                           'csrf_token': token},
#                                     headers=self.headers)
#         self.assertEqual(response.status_code, status.SEE_OTHER)

#         # Get the next page in the process. This should be the verify_user
#         # stage.
#         next_page = urlparse(response.headers['Location'])
#         self.assertIn('verify_user', next_page.path)
#         response = self.client.get(next_page.path)
#         self.assertIn(
#             b'Your account does not currently have any endorsed categories.',
#             response.data,
#             'User should be informed that they have no endorsements.'
#         )

#     def test_some_categories(self):
#         """User is endorsed (auto or otherwise) for some categories."""
#         self.token = generate_token('1234', 'foo@bar.com', 'foouser',
#                                     scope=[scopes.CREATE_SUBMISSION,
#                                            scopes.EDIT_SUBMISSION,
#                                            scopes.VIEW_SUBMISSION,
#                                            scopes.READ_UPLOAD,
#                                            scopes.WRITE_UPLOAD,
#                                            scopes.DELETE_UPLOAD_FILE],
#                                     endorsements=["cs.DL","cs.AI"])
#         self.headers = {'Authorization': self.token}

#         # Get the submission creation page.
#         response = self.client.get('/')
#         self.assertEqual(response.status_code, status.OK)
#         self.assertEqual(response.content_type, 'text/html; charset=utf-8')
#         token = self._parse_csrf_token(response)

#         # Create a submission.
#         response = self.client.post('/',
#                                     data={'new': 'new',
#                                           'csrf_token': token},
#                                     headers=self.headers)
#         self.assertEqual(response.status_code, status.SEE_OTHER)

#         # Get the next page in the process. This should be the verify_user
#         # stage.
#         next_page = urlparse(response.headers['Location'])
#         self.assertIn('verify_user', next_page.path)
#         response = self.client.get(next_page.path)
#         self.assertIn(
#             b'You are currently endorsed for',
#             response.data,
#             'User should be informed that they have some endorsements.'
#         )

#     def test_some_archives(self):
#         """User is endorsed (auto or otherwise) for some whole archives."""
#         self.token = generate_token('1234', 'foo@bar.com', 'foouser',
#                                     scope=[scopes.CREATE_SUBMISSION,
#                                            scopes.EDIT_SUBMISSION,
#                                            scopes.VIEW_SUBMISSION,
#                                            scopes.READ_UPLOAD,
#                                            scopes.WRITE_UPLOAD,
#                                            scopes.DELETE_UPLOAD_FILE],
#                                     endorsements=["cs.*","math.*"])
#         self.headers = {'Authorization': self.token}

#         # Get the submission creation page.
#         response = self.client.get('/')
#         self.assertEqual(response.status_code, status.OK)
#         self.assertEqual(response.content_type, 'text/html; charset=utf-8')
#         token = self._parse_csrf_token(response)

#         # Create a submission.
#         response = self.client.post('/',
#                                     data={'new': 'new',
#                                           'csrf_token': token},
#                                     headers=self.headers)
#         self.assertEqual(response.status_code, status.SEE_OTHER)

#         # Get the next page in the process. This should be the verify_user
#         # stage.
#         next_page = urlparse(response.headers['Location'])
#         self.assertIn('verify_user', next_page.path)
#         response = self.client.get(next_page.path)
#         self.assertIn(
#             b'You are currently endorsed for',
#             response.data,
#             'User should be informed that they have some endorsements.'
#         )

#     def test_all_endorsements(self):
#         """User is endorsed for everything."""
#         self.token = generate_token('1234', 'foo@bar.com', 'foouser',
#                                     scope=[scopes.CREATE_SUBMISSION,
#                                            scopes.EDIT_SUBMISSION,
#                                            scopes.VIEW_SUBMISSION,
#                                            scopes.READ_UPLOAD,
#                                            scopes.WRITE_UPLOAD,
#                                            scopes.DELETE_UPLOAD_FILE],
#                                     endorsements=["*.*"])
#         self.headers = {'Authorization': self.token}

#         # Get the submission creation page.
#         response = self.client.get('/')
#         self.assertEqual(response.status_code, status.OK)
#         self.assertEqual(response.content_type, 'text/html; charset=utf-8')
#         token = self._parse_csrf_token(response)

#         # Create a submission.
#         response = self.client.post('/',
#                                     data={'new': 'new',
#                                           'csrf_token': token},
#                                     headers=self.headers)
#         self.assertEqual(response.status_code, status.SEE_OTHER)

#         # Get the next page in the process. This should be the verify_user
#         # stage.
#         next_page = urlparse(response.headers['Location'])
#         self.assertIn('verify_user', next_page.path)
#         response = self.client.get(next_page.path)
#         self.assertNotIn(
#             b'Your account does not currently have any endorsed categories.',
#             response.data,
#             'User should see no messaging about endorsement.'
#         )
#         self.assertNotIn(
#             b'You are currently endorsed for',
#             response.data,
#             'User should see no messaging about endorsement.'
#         )
