"""Tests for :mod:`submit_ce.controllers.jref`."""

from unittest import TestCase, mock
from werkzeug.datastructures import MultiDict
from http import HTTPStatus as status

from pytz import timezone
from datetime import timedelta, datetime
from arxiv.auth import auth, domain
from submit_ce.ui.tests import CtrlBase
import submit_ce.api.domain
from submit_ce.ui.controllers import jref


def mock_save(*events, submission_id=None):
    for event in events:
        event.submission_id = submission_id
    return mock.MagicMock(submission_id=submission_id), events


class TestJREFSubmission(CtrlBase):
    """Test behavior of :func:`.jref` controller."""

    def setUp(self):
        """Create an authenticated session."""

        # Specify the validity period for the session.
        start = datetime.now(tz=timezone('US/Eastern'))
        end = start + timedelta(seconds=36000)

    @mock.patch(f'{jref.__name__}.JREFForm.Meta.csrf', False)
    @mock.patch(f'{jref.__name__}.alerts')
    @mock.patch(f'{jref.__name__}.url_for')
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_GET_with_unannounced(self, mock_load, mock_url_for, mock_alerts):
        """GET request for an unannounced submission."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_announced=False,
                                arxiv_id=None, version=1)
        mock_load.return_value = (before, [])
        mock_url_for.return_value = "/url/for/submission/status"
        data, code, headers = jref.jref('GET', MultiDict(), self.session,
                                        submission_id)
        self.assertEqual(code, status.SEE_OTHER, "Returns See Other")
        self.assertIn('Location', headers, "Returns Location header")
        self.assertTrue(
            mock_url_for.called_with('ui.submission_status', submission_id=2),
            "Gets the URL for the submission status page"
        )
        self.assertEqual(headers['Location'], "/url/for/submission/status",
                         "Returns the URL for the submission status page")
        self.assertEqual(mock_alerts.flash_failure.call_count, 1,
                         "An informative message is shown to the user")

    @mock.patch(f'{jref.__name__}.JREFForm.Meta.csrf', False)
    @mock.patch(f'{jref.__name__}.alerts')
    @mock.patch(f'{jref.__name__}.url_for')
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_POST_with_unannounced(self, mock_load, mock_url_for, mock_alerts):
        """POST request for an unannounced submission."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_announced=False,
                                arxiv_id=None, version=1)
        mock_load.return_value = (before, [])
        mock_url_for.return_value = "/url/for/submission/status"
        params = MultiDict({'doi': '10.1000/182'})    # Valid.
        data, code, headers = jref.jref('POST', params, self.session,
                                        submission_id)
        self.assertEqual(code, status.SEE_OTHER, "Returns See Other")
        self.assertIn('Location', headers, "Returns Location header")
        self.assertTrue(
            mock_url_for.called_with('ui.submission_status', submission_id=2),
            "Gets the URL for the submission status page"
        )
        self.assertEqual(headers['Location'], "/url/for/submission/status",
                         "Returns the URL for the submission status page")
        self.assertEqual(mock_alerts.flash_failure.call_count, 1,
                         "An informative message is shown to the user")

    @mock.patch(f'{jref.__name__}.JREFForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_GET_with_announced(self, mock_load):
        """GET request for a announced submission."""
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
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_POST_with_announced(self, mock_load, mock_url_for, mock_alerts):
        """POST request for a announced submission."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id, is_announced=True,
                                arxiv_id='2002.01234', version=1)
        mock_load.return_value = (before, [])
        mock_url_for.return_value = "/url/for/submission/status"
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
            "Gets the URL for the submission status page"
        )
        self.assertEqual(headers['Location'], "/url/for/submission/status",
                         "Returns the URL for the submission status page")
        self.assertEqual(mock_alerts.flash_success.call_count, 1,
                         "An informative message is shown to the user")
