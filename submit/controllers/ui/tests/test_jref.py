"""Tests for :mod:`submit.controllers.jref`."""

from unittest import TestCase, mock
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError, NotFound
from wtforms import Form
from http import HTTPStatus as status
import arxiv.submission as events
from submit.controllers.ui import jref

from pytz import timezone
from datetime import timedelta, datetime
from arxiv_auth import auth, domain


def mock_save(*events, submission_id=None):
    for event in events:
        event.submission_id = submission_id
    return mock.MagicMock(submission_id=submission_id), events


class TestJREFSubmission(TestCase):
    """Test behavior of :func:`.jref` controller."""

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

    @mock.patch(f'{jref.__name__}.alerts')
    @mock.patch(f'{jref.__name__}.url_for')
    @mock.patch(f'{jref.__name__}.JREFForm.Meta.csrf', False)
    @mock.patch('arxiv.submission.load')
    def test_GET_with_unannounced(self, mock_load, mock_url_for, mock_alerts):
        """GET request for an unannounced ui-app."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_announced=False,
                                arxiv_id=None, version=1)
        mock_load.return_value = (before, [])
        mock_url_for.return_value = "/url/for/ui-app/status"
        data, code, headers = jref.jref('GET', MultiDict(), self.session,
                                        submission_id)
        self.assertEqual(code, status.SEE_OTHER, "Returns See Other")
        self.assertIn('Location', headers, "Returns Location header")
        self.assertTrue(
            mock_url_for.called_with('ui.submission_status', submission_id=2),
            "Gets the URL for the ui-app status page"
        )
        self.assertEqual(headers['Location'], "/url/for/ui-app/status",
                         "Returns the URL for the ui-app status page")
        self.assertEqual(mock_alerts.flash_failure.call_count, 1,
                         "An informative message is shown to the user")

    @mock.patch(f'{jref.__name__}.alerts')
    @mock.patch(f'{jref.__name__}.url_for')
    @mock.patch(f'{jref.__name__}.JREFForm.Meta.csrf', False)
    @mock.patch('arxiv.submission.load')
    def test_POST_with_unannounced(self, mock_load, mock_url_for, mock_alerts):
        """POST request for an unannounced ui-app."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_announced=False,
                                arxiv_id=None, version=1)
        mock_load.return_value = (before, [])
        mock_url_for.return_value = "/url/for/ui-app/status"
        params = MultiDict({'doi': '10.1000/182'})    # Valid.
        data, code, headers = jref.jref('POST', params, self.session,
                                        submission_id)
        self.assertEqual(code, status.SEE_OTHER, "Returns See Other")
        self.assertIn('Location', headers, "Returns Location header")
        self.assertTrue(
            mock_url_for.called_with('ui.submission_status', submission_id=2),
            "Gets the URL for the ui-app status page"
        )
        self.assertEqual(headers['Location'], "/url/for/ui-app/status",
                         "Returns the URL for the ui-app status page")
        self.assertEqual(mock_alerts.flash_failure.call_count, 1,
                         "An informative message is shown to the user")

    @mock.patch(f'{jref.__name__}.JREFForm.Meta.csrf', False)
    @mock.patch('arxiv.submission.load')
    def test_GET_with_announced(self, mock_load):
        """GET request for a announced ui-app."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id, is_announced=True,
                                arxiv_id='2002.01234', version=1)
        mock_load.return_value = (before, [])
        params = MultiDict()
        data, code, _ = jref.jref('GET', params, self.session, submission_id)
        self.assertEqual(code, status.OK, "Returns 200 OK")
        self.assertIn('form', data, "Returns form in response data")

    @mock.patch(f'{jref.__name__}.alerts')
    @mock.patch(f'{jref.__name__}.url_for')
    @mock.patch(f'{jref.__name__}.JREFForm.Meta.csrf', False)
    @mock.patch('arxiv.submission.load')
    @mock.patch(f'{jref.__name__}.save', mock_save)
    def test_POST_with_announced(self, mock_load, mock_url_for, mock_alerts):
        """POST request for a announced ui-app."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id, is_announced=True,
                                arxiv_id='2002.01234', version=1)
        mock_load.return_value = (before, [])
        mock_url_for.return_value = "/url/for/ui-app/status"
        params = MultiDict({'doi': '10.1000/182'})
        _, code, _ = jref.jref('POST', params, self.session, submission_id)
        self.assertEqual(code, status.OK, "Returns 200 OK")

        params['confirmed'] = True
        data, code, headers = jref.jref('POST', params, self.session,
                                        submission_id)
        self.assertEqual(code, status.SEE_OTHER, "Returns See Other")
        self.assertIn('Location', headers, "Returns Location header")
        self.assertTrue(
            mock_url_for.called_with('ui.submission_status', submission_id=2),
            "Gets the URL for the ui-app status page"
        )
        self.assertEqual(headers['Location'], "/url/for/ui-app/status",
                         "Returns the URL for the ui-app status page")
        self.assertEqual(mock_alerts.flash_success.call_count, 1,
                         "An informative message is shown to the user")
