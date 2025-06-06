"""Tests for :mod:`submit_ce.controllers.license`."""

from http import HTTPStatus as status
from unittest import mock

from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError, NotFound
from wtforms import Form

import submit_ce as events

from submit_ce.api.domain.event import SetLicense
from submit_ce.api.exceptions import SaveError
from submit_ce.ui.controllers.new import license

from submit_ce.ui.tests import CtrlBase
from submit_ce.ui.routes.flow_control import get_controllers_desire, STAGE_SUCCESS

class TestSetLicense(CtrlBase):
    """Test behavior of :func:`.license` controller."""


    @mock.patch('submit_ce.ui.controllers.new.license.LicenseForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_get_request_with_submission(self, mock_load):
        """GET request with a submission ID."""
        submission_id = 2
        mock_load.return_value = ( mock.MagicMock(submission_id=submission_id), [])

        rdata, code, _ = license.license('GET', MultiDict(), self.session,
                                         submission_id)
        self.assertEqual(code, status.OK, "Returns 200 OK")
        self.assertIsInstance(rdata['form'], Form, "Data includes a form")

    @mock.patch('submit_ce.ui.controllers.new.license.LicenseForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.backend.api.get_with_history')

    def test_get_request_with_nonexistant_submission(self, mock_load):
        """GET request with a submission ID."""
        submission_id = 2

        def raise_no_such_submission(*args, **kwargs):
            raise NotFound()

        mock_load.side_effect = raise_no_such_submission
        with self.assertRaises(NotFound):
            license.license('GET', MultiDict(), self.session, submission_id)

    @mock.patch('submit_ce.ui.controllers.new.license.LicenseForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_post_request(self, mock_load):
        """POST request with no data."""
        submission_id = 2
        mock_load.return_value = (
            mock.MagicMock(submission_id=submission_id), []
        )
        data, _, _ = license.license('POST', MultiDict(), self.session, submission_id)
        self.assertIsInstance(data['form'], Form, "Data includes a form")

    @mock.patch('submit_ce.ui.controllers.new.license.LicenseForm.Meta.csrf', False)
    @mock.patch('submit.controllers.ui.util.url_for')
    @mock.patch(f'submit_ce.ui.controllers.new.license.save')
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_post_request_with_data(self, mock_load, mock_save, mock_url_for):
        """POST request with `license` set."""
        # Event store does not complain; returns object with `submission_id`.
        submission_id = 2
        sub = mock.MagicMock(submission_id=submission_id, is_finalized=False)
        mock_load.return_value = (sub, [])
        mock_save.return_value = (sub, [])
        # `url_for` returns a URL (unsurprisingly).
        redirect_url = 'https://foo.bar.com/yes'
        mock_url_for.return_value = redirect_url

        form_data = MultiDict({
            'license': 'http://arxiv.org/licenses/nonexclusive-distrib/1.0/',
            'action': 'next'
        })
        data, code, headers = license.license('POST', form_data, self.session,
                                              submission_id)
        self.assertEqual(get_controllers_desire(data), STAGE_SUCCESS)


    @mock.patch(f'submit_ce.ui.controllers.new.license.LicenseForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.controllers.new.license.api.save')
    @mock.patch('submit_ce.ui.backend.api.get_with_history')

    def test_post_request_with_data(self, mock_load, mock_save):
        """POST request with `license` set and same license already on submission."""
        submission_id = 2
        arxiv_lic = 'http://arxiv.org/licenses/nonexclusive-distrib/1.0/'
        lic = mock.MagicMock(uri=arxiv_lic)
        sub = mock.MagicMock(submission_id=submission_id,
                             license=lic,
                             is_finalized=False)
        mock_load.return_value = (sub, [])
        mock_save.return_value = (sub, [])

        form_data = MultiDict({
            'license': arxiv_lic,
            'action': 'next'
        })
        data, code, headers = license.license('POST', form_data, self.session,
                                              submission_id)
        self.assertEqual(get_controllers_desire(data), STAGE_SUCCESS)

    @mock.patch(f'submit_ce.ui.controllers.new.license.LicenseForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.controllers.new.license.api.save')
    @mock.patch('submit_ce.ui.backend.api.get_with_history')

    def test_save_fails(self, mock_load, mock_save):
        """Event store flakes out on saving license selection."""
        submission_id = 2
        sub = mock.MagicMock(submission_id=submission_id, is_finalized=False)
        mock_load.return_value = (sub, [])

        # Event store does not complain; returns object with `submission_id`
        def raise_on_verify(*ev, **kwargs):
            if type(ev[0]) is SetLicense:
                raise SaveError("mocked error")
            ident = kwargs.get('submission_id', 2)
            return (mock.MagicMock(submission_id=ident), [])

        mock_save.side_effect = raise_on_verify
        params = MultiDict({
            'license': 'http://arxiv.org/licenses/nonexclusive-distrib/1.0/',
            'action': 'next'
        })
        try:
            license.license('POST', params, self.session, 2)
            self.fail('InternalServerError not raised')
        except InternalServerError as e:
            data = e.description
            self.assertIsInstance(data['form'], Form, "Data includes a form")
