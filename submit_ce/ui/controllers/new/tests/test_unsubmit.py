"""Tests for :mod:`submit_ce.controllers.unsubmit`."""

from unittest import mock
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import BadRequest
from wtforms import Form
from http import HTTPStatus as status
import pytest

from submit_ce.ui.controllers.new import unsubmit

from submit_ce.ui.tests import CtrlBase


class TestUnsubmit(CtrlBase):
    """Test behavior of :func:`.unsubmit` controller."""
    @pytest.mark.skip
    @mock.patch(f'{unsubmit.__name__}.UnsubmitForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_get_request_with_submission(self, mock_load):
        """GET request with a submission ID."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=True,
                                submitter_contact_verified=False)
        mock_load.return_value = (before, [])
        data, code, _ = unsubmit.unsubmit('GET', MultiDict(), self.session,
                                          submission_id)
        self.assertEqual(code, status.OK, "Returns 200 OK")
        self.assertIsInstance(data['form'], Form, "Data includes a form")

    @pytest.mark.skip
    @mock.patch(f'{unsubmit.__name__}.UnsubmitForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_post_request(self, mock_load):
        """POST request with no data."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=True,
                                submitter_contact_verified=False)
        mock_load.return_value = (before, [])
        params = MultiDict()
        try:
            unsubmit.unsubmit('POST', params, self.session, submission_id)
            self.fail('BadRequest not raised')
        except BadRequest as e:
            data = e.description
            self.assertIsInstance(data['form'], Form, "Data includes a form")

    @pytest.mark.skip
    @mock.patch(f'{unsubmit.__name__}.UnsubmitForm.Meta.csrf', False)
    @mock.patch(f'{unsubmit.__name__}.url_for')
    @mock.patch('arxiv.base.alerts.flash_success')
    @mock.patch('submit_ce.ui.backend.api.save')
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_post_request_with_data(self, mock_load, mock_save,
                                    mock_flash_success, mock_url_for):
        """POST request with `confirmed` set."""
        # Event store does not complain; returns object with `submission_id`.
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=True, is_announced=False)
        after = mock.MagicMock(submission_id=submission_id,
                               is_finalized=False, is_announced=False)
        mock_load.return_value = (before, [])
        mock_save.return_value = (after, [])
        mock_flash_success.return_value = None
        mock_url_for.return_value = 'https://foo.bar.com/yes'

        form_data = MultiDict({'confirmed': True})
        _, code, _ = unsubmit.unsubmit('POST', form_data, self.session,
                                       submission_id)
        self.assertEqual(code, status.SEE_OTHER, "Returns redirect")
