"""Tests for :mod:`submit.controllers.classification`."""

from unittest import TestCase, mock

from arxiv_auth import domain, auth
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError, NotFound, BadRequest
from wtforms import Form
from http import HTTPStatus as status
import arxiv.submission as events
from submit.controllers.ui.new import classification

from pytz import timezone
from datetime import timedelta, datetime

class TestClassification(TestCase):
    """Test behavior of :func:`.classification` controller."""

    def setUp(self):
        """Create an authenticated session."""
        # Specify the validity period for the session.
        start = datetime.now(tz=timezone('US/Eastern'))
        end = start + timedelta(seconds=36000)
        self.session = domain.Session(
            session_id='123-session-abc',
            start_time=start, end_time=end,
            user=domain.User(
                user_id='235678',
                email='foo@foo.com',
                username='foouser',
                name=domain.UserFullName(forename="Jane",surname= "Bloggs",suffix= "III"),
                profile=domain.UserProfile(
                    affiliation="FSU",
                    rank=3,
                    country="de",
                    default_category=domain.Category('astro-ph.GA'),
                    submission_groups=['grp_physics']
                )
            ),
            authorizations=domain.Authorizations(
                scopes=[auth.scopes.CREATE_SUBMISSION,
                        auth.scopes.EDIT_SUBMISSION,
                        auth.scopes.VIEW_SUBMISSION],
                endorsements=[domain.Category('astro-ph.CO'),
                              domain.Category('astro-ph.GA')]
            )
        )

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf',
                False)
    @mock.patch('arxiv.submission.load')
    def test_get_request_with_submission(self, mock_load):
        """GET request with a ui-app ID."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False,
                                is_announced=False, version=1, arxiv_id=None)
        mock_load.return_value = (before, [])
        data, code, _ = classification.classification('GET', MultiDict(),
                                                      self.session,
                                                      submission_id)
        self.assertEqual(code, status.OK, "Returns 200 OK")
        self.assertIsInstance(data['form'], Form, "Data includes a form")

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf',
                False)
    @mock.patch('arxiv.submission.load')
    def test_get_request_with_nonexistant_submission(self, mock_load):
        """GET request with a ui-app ID."""
        submission_id = 2

        def raise_no_such_submission(*args, **kwargs):
            raise events.exceptions.NoSuchSubmission('Nada')

        mock_load.side_effect = raise_no_such_submission
        with self.assertRaises(NotFound):
            classification.classification('GET', MultiDict(), self.session,
                                          submission_id)

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf',
                False)
    @mock.patch('arxiv.submission.load')
    def test_post_request(self, mock_load):
        """POST request with no data."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False,
                                is_announced=False, version=1, arxiv_id=None)
        mock_load.return_value = (before, [])

        data, _, _ = classification.classification('POST', MultiDict(), self.session,
                                                   submission_id)
        self.assertIsInstance(data['form'], Form, "Data includes a form")

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf',
                False)
    @mock.patch(f'{classification.__name__}.save')
    @mock.patch('arxiv.submission.load')
    def test_post_with_invalid_category(self, mock_load, mock_save):
        """POST request with invalid category."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False,
                                is_announced=False, version=1, arxiv_id=None)
        mock_load.return_value = (before, [])
        mock_save.return_value = (before, [])

        params = MultiDict({'category': 'astro-ph'})  # <- expired

        data, _, _ = classification.classification('POST', params, self.session,
                                                   submission_id)        
        self.assertIsInstance(data['form'], Form, "Data includes a form")

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf',
                False)
    @mock.patch(f'{classification.__name__}.save')
    @mock.patch('arxiv.submission.load')
    def test_post_with_category(self, mock_load, mock_save):
        """POST request with valid category."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False,
                                is_announced=False, version=1, arxiv_id=None)
        mock_clsn = mock.MagicMock(category='astro-ph.CO')
        after = mock.MagicMock(submission_id=submission_id,
                               is_finalized=False,
                               primary_classification=mock_clsn,
                               is_announced=False, version=1, arxiv_id=None)
        mock_load.return_value = (before, [])
        mock_save.return_value = (after, [])
        params = MultiDict({'category': 'astro-ph.CO'})
        data, code, _ = classification.classification('POST', params,
                                                      self.session,
                                                      submission_id)
        self.assertEqual(code, status.OK, "Returns 200 OK")

        self.assertIsInstance(data['form'], Form, "Data includes a form")


class TestCrossList(TestCase):
    """Test behavior of :func:`.cross_list` controller."""

    def setUp(self):
        """Create an authenticated session."""
        # Specify the validity period for the session.
        start = datetime.now(tz=timezone('US/Eastern'))
        end = start + timedelta(seconds=36000)
        self.session = domain.Session(
            session_id='123-session-abc',
            start_time=start, end_time=end,
            user=domain.User(
                user_id='235678',
                email='foo@foo.com',
                username='foouser',
                name=domain.UserFullName(forename="Jane",surname= "Bloggs",suffix= "III"),
                profile=domain.UserProfile(
                    affiliation="FSU",
                    rank=3,
                    country="de",
                    default_category=domain.Category('astro-ph.GA'),
                    submission_groups=['grp_physics']
                )
            ),
            authorizations=domain.Authorizations(
                scopes=[auth.scopes.CREATE_SUBMISSION,
                        auth.scopes.EDIT_SUBMISSION,
                        auth.scopes.VIEW_SUBMISSION],
                endorsements=[domain.Category('astro-ph.CO'),
                              domain.Category('astro-ph.GA')]
            )
        )

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf',
                False)
    @mock.patch('arxiv.submission.load')
    def test_get_request_with_submission(self, mock_load):
        """GET request with a ui-app ID."""
        submission_id = 2
        mock_clsn = mock.MagicMock(category='astro-ph.EP')
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False,
                                primary_classification=mock_clsn,
                                is_announced=False, version=1, arxiv_id=None)
        mock_load.return_value = (before, [])
        params = MultiDict()
        data, code, _ = classification.cross_list('GET', params, self.session,
                                                  submission_id)
        self.assertEqual(code, status.OK, "Returns 200 OK")
        self.assertIsInstance(data['form'], Form, "Data includes a form")

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf',
                False)
    @mock.patch('arxiv.submission.load')
    def test_get_request_with_nonexistant_submission(self, mock_load):
        """GET request with a ui-app ID."""
        submission_id = 2

        def raise_no_such_submission(*args, **kwargs):
            raise events.exceptions.NoSuchSubmission('Nada')

        mock_load.side_effect = raise_no_such_submission
        with self.assertRaises(NotFound):
            classification.cross_list('GET', MultiDict(), self.session,
                                      submission_id)

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf',
                False)
    @mock.patch('arxiv.submission.load')
    def test_post_request(self, mock_load):
        """POST request with no data."""
        submission_id = 2
        mock_clsn = mock.MagicMock(category='astro-ph.EP')
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False,
                                primary_classification=mock_clsn,
                                is_announced=False, version=1, arxiv_id=None)
        mock_load.return_value = (before, [])

        data, _, _ = classification.cross_list('POST', MultiDict(), self.session,
                                               submission_id)
        self.assertIsInstance(data['form'], Form, "Data includes a form")

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf',
                False)
    @mock.patch(f'{classification.__name__}.save')
    @mock.patch('arxiv.submission.load')
    def test_post_with_invalid_category(self, mock_load, mock_save):
        """POST request with invalid category."""
        submission_id = 2
        mock_clsn = mock.MagicMock(category='astro-ph.EP')
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False,
                                primary_classification=mock_clsn,
                                is_announced=False, version=1, arxiv_id=None)
        mock_load.return_value = (before, [])
        mock_save.return_value = (before, [])
        params = MultiDict({'category': 'astro-ph'})  # <- expired
        data, _, _ = classification.classification('POST', params, self.session,
                                                   submission_id)        
        self.assertIsInstance(data['form'], Form, "Data includes a form")

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf',
                False)
    @mock.patch(f'{classification.__name__}.save')
    @mock.patch('arxiv.submission.load')
    def test_post_with_category(self, mock_load, mock_save):
        """POST request with valid category."""
        submission_id = 2
        mock_clsn = mock.MagicMock(category='astro-ph.EP')
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False,
                                primary_classification=mock_clsn,
                                primary_category='astro-ph.EP',
                                is_announced=False, version=1, arxiv_id=None)
        after = mock.MagicMock(submission_id=submission_id, is_finalized=False,
                               primary_classification=mock_clsn,
                               primary_category='astro-ph.EP',
                               secondary_categories=[
                                   mock.MagicMock(category='astro-ph.CO')
                               ],
                               is_announced=False, version=1, arxiv_id=None)
        mock_load.return_value = (before, [])
        mock_save.return_value = (after, [])
        params = MultiDict({'category': 'astro-ph.CO'})
        data, code, _ = classification.cross_list('POST', params, self.session,
                                                  submission_id)
        self.assertEqual(code, status.OK, "Returns 200 OK")
        self.assertIsInstance(data['form'], Form, "Data includes a form")
