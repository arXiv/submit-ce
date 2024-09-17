"""Tests for the ui-app application as a whole."""

import os
import re
import tempfile
from unittest import TestCase, mock
from urllib.parse import urlparse

from arxiv_auth.helpers import generate_token

from submit.factory import create_ui_web_app
from arxiv.submission.services import classic
from arxiv_auth.auth import scopes
from arxiv_auth.domain import Category
from http import HTTPStatus as status
from arxiv.submission.domain.event import *
from arxiv.submission.domain.agent import User
from arxiv.submission.domain.submission import Author, SubmissionContent
from arxiv.submission import save
from .csrf_util import parse_csrf_token


# TODO: finish building out this test suite. The current tests run up to
# file upload. Once the remaining stages have stabilized, this should have
# tests from end to end.
# TODO: add a test where the user tries to jump around in the workflow, and
# verify that stage completion order is enforced.
class TestSubmissionWorkflow(TestCase):
    """Tests that progress through the ui-app workflow in various ways."""

    @mock.patch('arxiv.submission.StreamPublisher', mock.MagicMock())
    def setUp(self):
        """Create an application instance."""
        self.app = create_ui_web_app({"CLASSIC_SESSION_HASH":"lklk23$jk", "SESSION_DURATION":6000, "CLASSIC_COOKIE_NAME": "tapir_session"})
        os.environ['JWT_SECRET'] = str(self.app.config.get('JWT_SECRET'))
        _, self.db = tempfile.mkstemp(suffix='.db')
        self.app.config['CLASSIC_DATABASE_URI'] = f'sqlite:///{self.db}'
        self.token = generate_token('1234', 'foo@bar.com', 'foouser',
                                    scope=[scopes.CREATE_SUBMISSION,
                                           scopes.EDIT_SUBMISSION,
                                           scopes.VIEW_SUBMISSION,
                                           scopes.READ_UPLOAD,
                                           scopes.WRITE_UPLOAD,
                                           scopes.DELETE_UPLOAD_FILE],
                                    endorsements=[
                                        Category('astro-ph.GA'),
                                        Category('astro-ph.CO'),
                                    ])
        self.headers = {'Authorization': self.token}
        self.client = self.app.test_client()
        with self.app.app_context():
            classic.create_all()

    def tearDown(self):
        """Remove the temporary database."""
        os.remove(self.db)

    def _parse_csrf_token(self, response):
        try:
            return parse_csrf_token(response)
        except AttributeError:
            self.fail('Could not find CSRF token')


    @mock.patch('arxiv.submission.core.StreamPublisher', mock.MagicMock())
    def test_create_submission(self):
        """User creates a new ui-app, and proceeds up to upload stage."""
        # Get the ui-app creation page.
        response = self.client.get('/', headers=self.headers)
        self.assertEqual(response.status_code, status.OK)
        self.assertEqual(response.content_type, 'text/html; charset=utf-8')
        token = self._parse_csrf_token(response)

        # Create a ui-app.
        response = self.client.post('/',
                                    data={'new': 'new',
                                          'csrf_token': token},
                                    headers=self.headers)
        self.assertEqual(response.status_code, status.SEE_OTHER)

        # Get the next page in the process. This should be the verify_user
        # stage.
        next_page = urlparse(response.headers['Location'])
        self.assertIn('verify_user', next_page.path)
        response = self.client.get(next_page.path, headers=self.headers)
        self.assertIn(
            b'By checking this box, I verify that my user information is'
            b' correct.',
            response.data
        )
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
        response = self.client.get(next_page.path, headers=self.headers)
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
        response = self.client.get(next_page.path, headers=self.headers)
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
        response = self.client.get(next_page.path, headers=self.headers)
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
        response = self.client.get(next_page.path, headers=self.headers)
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
        response = self.client.get(next_page.path, headers=self.headers)
        self.assertIn(b'Choose Cross-List Classifications', response.data)
        token = self._parse_csrf_token(response)

        # Submit the cross-list category page.
        response = self.client.post(next_page.path,
                                    data={'category': 'astro-ph.CO',
                                          'csrf_token': token},
                                    headers=self.headers)
        self.assertEqual(response.status_code, status.OK)

        response = self.client.post(next_page.path,
                                    data={'action':'next'},
                                    headers=self.headers)
        self.assertEqual(response.status_code, status.SEE_OTHER)

        # Get the next page in the process. This is the file upload stage.
        next_page = urlparse(response.headers['Location'])
        self.assertIn('upload', next_page.path)
        response = self.client.get(next_page.path, headers=self.headers)
        self.assertIn(b'Upload Files', response.data)
        token = self._parse_csrf_token(response)


class TestEndorsementMessaging(TestCase):
    """Verify submitter is shown appropriate messaging about endoresement."""

    def setUp(self):
        """Create an application instance."""
        self.app = create_ui_web_app({"CLASSIC_SESSION_HASH":"lklk23$jk", "SESSION_DURATION":6000, "CLASSIC_COOKIE_NAME": "tapir_session"})
        os.environ['JWT_SECRET'] = str(self.app.config.get('JWT_SECRET', 'fo'))
        _, self.db = tempfile.mkstemp(suffix='.db')
        self.app.config['CLASSIC_DATABASE_URI'] = f'sqlite:///{self.db}'
        self.client = self.app.test_client()
        with self.app.app_context():
            classic.create_all()

    def tearDown(self):
        """Remove the temporary database."""
        os.remove(self.db)

    def _parse_csrf_token(self, response):
        try:
            return parse_csrf_token(response)
        except AttributeError:
            self.fail('Could not find CSRF token')
        return token

    @mock.patch('arxiv.submission.core.StreamPublisher', mock.MagicMock())
    def test_no_endorsements(self):
        """User is not endorsed (auto or otherwise) for anything."""
        self.token = generate_token('1234', 'foo@bar.com', 'foouser',
                                    scope=[scopes.CREATE_SUBMISSION,
                                           scopes.EDIT_SUBMISSION,
                                           scopes.VIEW_SUBMISSION,
                                           scopes.READ_UPLOAD,
                                           scopes.WRITE_UPLOAD,
                                           scopes.DELETE_UPLOAD_FILE],
                                    endorsements=[])
        self.headers = {'Authorization': self.token}

        # Get the ui-app creation page.
        response = self.client.get('/', headers=self.headers)
        self.assertEqual(response.status_code, status.OK)
        self.assertEqual(response.content_type, 'text/html; charset=utf-8')
        token = self._parse_csrf_token(response)

        # Create a ui-app.
        response = self.client.post('/',
                                    data={'new': 'new',
                                          'csrf_token': token},
                                    headers=self.headers)
        self.assertEqual(response.status_code, status.SEE_OTHER)

        # Get the next page in the process. This should be the verify_user
        # stage.
        next_page = urlparse(response.headers['Location'])
        self.assertIn('verify_user', next_page.path)
        response = self.client.get(next_page.path, headers=self.headers)
        self.assertIn(
            b'Your account does not currently have any endorsed categories.',
            response.data,
            'User should be informed that they have no endorsements.'
        )

    @mock.patch('arxiv.submission.core.StreamPublisher', mock.MagicMock())
    def test_some_categories(self):
        """User is endorsed (auto or otherwise) for some categories."""
        self.token = generate_token('1234', 'foo@bar.com', 'foouser',
                                    scope=[scopes.CREATE_SUBMISSION,
                                           scopes.EDIT_SUBMISSION,
                                           scopes.VIEW_SUBMISSION,
                                           scopes.READ_UPLOAD,
                                           scopes.WRITE_UPLOAD,
                                           scopes.DELETE_UPLOAD_FILE],
                                    endorsements=[Category("cs.DL"),
                                                  Category("cs.AI")])
        self.headers = {'Authorization': self.token}

        # Get the ui-app creation page.
        response = self.client.get('/', headers=self.headers)
        self.assertEqual(response.status_code, status.OK)
        self.assertEqual(response.content_type, 'text/html; charset=utf-8')
        token = self._parse_csrf_token(response)

        # Create a ui-app.
        response = self.client.post('/',
                                    data={'new': 'new',
                                          'csrf_token': token},
                                    headers=self.headers)
        self.assertEqual(response.status_code, status.SEE_OTHER)

        # Get the next page in the process. This should be the verify_user
        # stage.
        next_page = urlparse(response.headers['Location'])
        self.assertIn('verify_user', next_page.path)
        response = self.client.get(next_page.path, headers=self.headers)
        self.assertIn(
            b'You are currently endorsed for',
            response.data,
            'User should be informed that they have some endorsements.'
        )

    @mock.patch('arxiv.submission.core.StreamPublisher', mock.MagicMock())
    def test_some_archives(self):
        """User is endorsed (auto or otherwise) for some whole archives."""
        self.token = generate_token('1234', 'foo@bar.com', 'foouser',
                                    scope=[scopes.CREATE_SUBMISSION,
                                           scopes.EDIT_SUBMISSION,
                                           scopes.VIEW_SUBMISSION,
                                           scopes.READ_UPLOAD,
                                           scopes.WRITE_UPLOAD,
                                           scopes.DELETE_UPLOAD_FILE],
                                    endorsements=[Category("cs.*"),
                                                  Category("math.*")])
        self.headers = {'Authorization': self.token}

        # Get the ui-app creation page.
        response = self.client.get('/', headers=self.headers)
        self.assertEqual(response.status_code, status.OK)
        self.assertEqual(response.content_type, 'text/html; charset=utf-8')
        token = self._parse_csrf_token(response)

        # Create a ui-app.
        response = self.client.post('/',
                                    data={'new': 'new',
                                          'csrf_token': token},
                                    headers=self.headers)
        self.assertEqual(response.status_code, status.SEE_OTHER)

        # Get the next page in the process. This should be the verify_user
        # stage.
        next_page = urlparse(response.headers['Location'])
        self.assertIn('verify_user', next_page.path)
        response = self.client.get(next_page.path, headers=self.headers)
        self.assertIn(
            b'You are currently endorsed for',
            response.data,
            'User should be informed that they have some endorsements.'
        )

    @mock.patch('arxiv.submission.core.StreamPublisher', mock.MagicMock())
    def test_all_endorsements(self):
        """User is endorsed for everything."""
        self.token = generate_token('1234', 'foo@bar.com', 'foouser',
                                    scope=[scopes.CREATE_SUBMISSION,
                                           scopes.EDIT_SUBMISSION,
                                           scopes.VIEW_SUBMISSION,
                                           scopes.READ_UPLOAD,
                                           scopes.WRITE_UPLOAD,
                                           scopes.DELETE_UPLOAD_FILE],
                                    endorsements=["*.*"])
        self.headers = {'Authorization': self.token}

        # Get the ui-app creation page.
        response = self.client.get('/', headers=self.headers)
        self.assertEqual(response.status_code, status.OK)
        self.assertEqual(response.content_type, 'text/html; charset=utf-8')
        token = self._parse_csrf_token(response)

        # Create a ui-app.
        response = self.client.post('/',
                                    data={'new': 'new',
                                          'csrf_token': token},
                                    headers=self.headers)
        self.assertEqual(response.status_code, status.SEE_OTHER)

        # Get the next page in the process. This should be the verify_user
        # stage.
        next_page = urlparse(response.headers['Location'])
        self.assertIn('verify_user', next_page.path)
        response = self.client.get(next_page.path, headers=self.headers)
        self.assertNotIn(
            b'Your account does not currently have any endorsed categories.',
            response.data,
            'User should see no messaging about endorsement.'
        )
        self.assertNotIn(
            b'You are currently endorsed for',
            response.data,
            'User should see no messaging about endorsement.'
        )


class TestJREFWorkflow(TestCase):
    """Tests that progress through the JREF workflow."""

    @mock.patch('arxiv.submission.core.StreamPublisher', mock.MagicMock())
    def setUp(self):
        """Create an application instance."""
        self.app = create_ui_web_app({"CLASSIC_SESSION_HASH":"lklk23$jk", "SESSION_DURATION":6000, "CLASSIC_COOKIE_NAME": "tapir_session"})
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
                                        Category('astro-ph.GA'),
                                        Category('astro-ph.CO'),
                                    ])
        self.headers = {'Authorization': self.token}
        self.client = self.app.test_client()

        # Create and announce a ui-app.
        with self.app.app_context():
            classic.create_all()
            session = classic.current_session()

            cc0 = 'http://creativecommons.org/publicdomain/zero/1.0/'
            self.submission, _ = save(
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

            # announced!
            db_submission = session.query(classic.models.Submission) \
                .get(self.submission.submission_id)
            db_submission.status = classic.models.Submission.ANNOUNCED
            db_document = classic.models.Document(paper_id='1234.5678')
            db_submission.doc_paper_id = '1234.5678'
            db_submission.document = db_document
            session.add(db_submission)
            session.add(db_document)
            session.commit()

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

    @mock.patch('arxiv.submission.core.StreamPublisher', mock.MagicMock())
    def test_create_submission(self):
        """User creates a new ui-app, and proceeds up to upload stage."""
        # Get the JREF page.
        endpoint = f'/{self.submission_id}/jref'
        response = self.client.get(endpoint, headers=self.headers)
        self.assertEqual(response.status_code, status.OK)
        self.assertEqual(response.content_type, 'text/html; charset=utf-8')
        self.assertIn(b'Journal reference', response.data)
        token = self._parse_csrf_token(response)

        # Set the DOI, journal reference, report number.
        request_data = {'doi': '10.1000/182',
                        'journal_ref': 'foo journal 1992',
                        'report_num': 'abc report 42',
                        'csrf_token': token}
        response = self.client.post(endpoint, data=request_data,
                                    headers=self.headers)
        self.assertEqual(response.status_code, status.OK)
        self.assertEqual(response.content_type, 'text/html; charset=utf-8')
        self.assertIn(b'Confirm and Submit', response.data)
        token = self._parse_csrf_token(response)

        request_data['confirmed'] = True
        request_data['csrf_token'] = token
        response = self.client.post(endpoint, data=request_data,
                                    headers=self.headers)
        self.assertEqual(response.status_code, status.SEE_OTHER)

        with self.app.app_context():
            session = classic.current_session()
            # What happened.
            db_submission = session.query(classic.models.Submission) \
                .filter(classic.models.Submission.doc_paper_id == '1234.5678')
            self.assertEqual(db_submission.count(), 2,
                             "Creates a second row for the JREF")


class TestWithdrawalWorkflow(TestCase):
    """Tests that progress through the withdrawal request workflow."""

    @mock.patch('arxiv.submission.core.StreamPublisher', mock.MagicMock())
    def setUp(self):
        """Create an application instance."""
        self.app = create_ui_web_app({"CLASSIC_SESSION_HASH":"lklk23$jk", "SESSION_DURATION":6000, "CLASSIC_COOKIE_NAME": "tapir_session"})
        os.environ['JWT_SECRET'] = str(self.app.config.get('JWT_SECRET', 'fo'))
        _, self.db = tempfile.mkstemp(suffix='.db')
        self.app.config['CLASSIC_DATABASE_URI'] = f'sqlite:///{self.db}'
        self.user = User('1234', 'foo@bar.com',
                         endorsements=['astro-ph.GA', 'astro-ph.CO'])
        self.token = generate_token('1234', 'foo@bar.com', 'foouser',
                                    scope=[scopes.CREATE_SUBMISSION,
                                           scopes.EDIT_SUBMISSION,
                                           scopes.VIEW_SUBMISSION,
                                           scopes.READ_UPLOAD,
                                           scopes.WRITE_UPLOAD,
                                           scopes.DELETE_UPLOAD_FILE],
                                    endorsements=[
                                        Category('astro-ph.GA'),
                                        Category('astro-ph.CO'),
                                    ])
        self.headers = {'Authorization': self.token}
        self.client = self.app.test_client()

        # Create and announce a ui-app.
        with self.app.app_context():
            classic.create_all()
            session = classic.current_session()

            cc0 = 'http://creativecommons.org/publicdomain/zero/1.0/'
            self.submission, _ = save(
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

            # announced!
            db_submission = session.query(classic.models.Submission) \
                .get(self.submission.submission_id)
            db_submission.status = classic.models.Submission.ANNOUNCED
            db_document = classic.models.Document(paper_id='1234.5678')
            db_submission.doc_paper_id = '1234.5678'
            db_submission.document = db_document
            session.add(db_submission)
            session.add(db_document)
            session.commit()

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

    @mock.patch('arxiv.submission.core.StreamPublisher', mock.MagicMock())
    def test_request_withdrawal(self):
        """User requests withdrawal of a announced ui-app."""
        # Get the JREF page.
        endpoint = f'/{self.submission_id}/withdraw'
        response = self.client.get(endpoint, headers=self.headers)
        self.assertEqual(response.status_code, status.OK)
        self.assertEqual(response.content_type, 'text/html; charset=utf-8')
        self.assertIn(b'Request withdrawal', response.data)
        token = self._parse_csrf_token(response)

        # Set the withdrawal reason, but make it huge.
        request_data = {'withdrawal_reason': 'This is the reason' * 400,
                        'csrf_token': token}
        response = self.client.post(endpoint, data=request_data,
                                    headers=self.headers)
        self.assertEqual(response.status_code, status.OK)
        token = self._parse_csrf_token(response)

        # Set the withdrawal reason to something reasonable (ha).
        request_data = {'withdrawal_reason': 'This is the reason',
                        'csrf_token': token}
        response = self.client.post(endpoint, data=request_data,
                                    headers=self.headers)
        self.assertEqual(response.status_code, status.OK)
        self.assertEqual(response.content_type, 'text/html; charset=utf-8')
        self.assertIn(b'Confirm and Submit', response.data)
        token = self._parse_csrf_token(response)

        # Confirm the withdrawal request.
        request_data['confirmed'] = True
        request_data['csrf_token'] = token
        response = self.client.post(endpoint, data=request_data,
                                    headers=self.headers)
        self.assertEqual(response.status_code, status.SEE_OTHER)

        with self.app.app_context():
            session = classic.current_session()
            # What happened.
            db_submissions = session.query(classic.models.Submission) \
                .filter(classic.models.Submission.doc_paper_id == '1234.5678')
            self.assertEqual(db_submissions.count(), 2,
                             "Creates a second row for the withdrawal")
            db_submission = db_submissions \
                .order_by(classic.models.Submission.submission_id.desc()) \
                .first()
            self.assertEqual(db_submission.type,
                             classic.models.Submission.WITHDRAWAL)


class TestUnsubmitWorkflow(TestCase):
    """Tests that progress through the unsubmit workflow."""

    @mock.patch('arxiv.submission.core.StreamPublisher', mock.MagicMock())
    def setUp(self):
        """Create an application instance."""
        self.app = create_ui_web_app({"CLASSIC_SESSION_HASH":"lklk23$jk", "SESSION_DURATION":6000, "CLASSIC_COOKIE_NAME": "tapir_session"})
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
                                        Category('astro-ph.GA'),
                                        Category('astro-ph.CO'),
                                    ])
        self.headers = {'Authorization': self.token}
        self.client = self.app.test_client()

        # Create a finalized ui-app.
        with self.app.app_context():
            classic.create_all()
            session = classic.current_session()

            cc0 = 'http://creativecommons.org/publicdomain/zero/1.0/'
            self.submission, _ = save(
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

    @mock.patch('arxiv.submission.core.StreamPublisher', mock.MagicMock())
    def test_unsubmit_submission(self):
        """User unsubmits a ui-app."""
        # Get the unsubmit confirmation page.
        endpoint = f'/{self.submission_id}/unsubmit'
        response = self.client.get(endpoint, headers=self.headers)
        self.assertEqual(response.status_code, status.OK)
        self.assertEqual(response.content_type, 'text/html; charset=utf-8')
        self.assertIn(b'Unsubmit This Submission', response.data)
        token = self._parse_csrf_token(response)

        # Confirm the ui-app should be unsubmitted
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
