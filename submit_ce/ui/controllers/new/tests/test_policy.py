"""Tests for :mod:`submit_ce.controllers.policy`."""

from http import HTTPStatus as status
from unittest import mock

from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError, NotFound
from wtforms import Form

import submit_ce as events

from submit_ce.api.domain.event import ConfirmPolicy
from submit_ce.api.exceptions import NoSuchSubmission, SaveError
from submit_ce.ui.controllers.new import policy

import submit_ce.api.domain
from submit_ce.ui.tests import CtrlBase
from submit_ce.ui.routes.flow_control import get_controllers_desire, STAGE_SUCCESS

class TestConfirmPolicy(CtrlBase):
    """Test behavior of :func:`.policy` controller."""

    @mock.patch(f'{policy.__name__}.PolicyForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_get_request_with_submission(self, mock_load):
        """GET request with a submission ID."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False,
                                submitter_accepts_policy=False)
        mock_load.return_value = (before, [])
        data = MultiDict()

        data, code, _ = policy.policy('GET', data, self.session, submission_id)
        self.assertEqual(code, status.OK, "Returns 200 OK")
        self.assertIsInstance(data['form'], Form, "Data includes a form")

    @mock.patch(f'{policy.__name__}.PolicyForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_get_request_with_nonexistant_submission(self, mock_load):
        """GET request with a submission ID."""
        submission_id = 2

        def raise_no_such_submission(*args, **kwargs):
            raise NoSuchSubmission('Nada')

        mock_load.side_effect = raise_no_such_submission
        with self.assertRaises(NotFound):
            policy.policy('GET', MultiDict(), self.session,  submission_id)

    @mock.patch(f'{policy.__name__}.PolicyForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_post_request(self, mock_load):
        """POST request with no data."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False,
                                submitter_accepts_policy=False)
        mock_load.return_value = (before, [])

        params = MultiDict()
        data, _, _ = policy.policy('POST', params, self.session, submission_id)
        self.assertIsInstance(data['form'], Form, "Data includes a form")

    @mock.patch(f'{policy.__name__}.PolicyForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_not_author_no_proxy(self, mock_load):
        """User indicates they are not author, but also not proxy."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False,
                                submitter_accepts_policy=False)
        mock_load.return_value = (before, [])
        params = MultiDict({})
        data, _, _ = policy.policy('POST', params, self.session, submission_id)
        self.assertIsInstance(data['form'], Form, "Data includes a form")


    @mock.patch(f'{policy.__name__}.PolicyForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.backend.api.save')
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_post_request_with_data(self, mock_load, mock_save):
        """POST request with `policy` set."""
        # Event store does not complain; returns object with `submission_id`.
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False,
                                submitter_accepts_policy=False)
        after = mock.MagicMock(submission_id=submission_id, is_finalized=False)
        mock_load.return_value = (before, [])
        mock_save.return_value = (after, [])
        #mock_url_for.return_value = 'https://foo.bar.com/yes'

        params = MultiDict({'policy': 'y', 'policy_id': 'x1_cheese_policy_awesome', 'action': 'next'})
        data, code, _ = policy.policy('POST', params, self.session, submission_id)
        self.assertEqual(code, status.OK)
        self.assertEqual(get_controllers_desire(data), STAGE_SUCCESS)


    @mock.patch(f'{policy.__name__}.PolicyForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.backend.api.save')
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_post_request_with_data_already_accepted(self, mock_load, mock_save):
        """POST request with `policy` y and already set on the submission."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False,
                                submitter_accepts_policy=True)
        after = mock.MagicMock(submission_id=submission_id, is_finalized=False)
        mock_load.return_value = (before, [])
        mock_save.return_value = (after, [])
        #mock_url_for.return_value = 'https://foo.bar.com/yes'

        params = MultiDict({'policy': 'y', 'policy_id': 'policy_234', 'action': 'next'})
        data, code, _ = policy.policy('POST', params, self.session, submission_id)
        self.assertEqual(code, status.OK)
        self.assertEqual(get_controllers_desire(data), STAGE_SUCCESS)
        
    @mock.patch(f'{policy.__name__}.PolicyForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.backend.api.save')
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_save_fails(self, mock_load, mock_save):
        """Event store flakes out on saving policy acceptance."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False,
                                submitter_accepts_policy=False)
        mock_load.return_value = (before, [])

        # Event store does not complain; returns object with `submission_id`
        def raise_on_policy(*ev, **kwargs):
            if type(ev[0]) is ConfirmPolicy:
                raise SaveError('the end of the world as we know it')
            ident = kwargs.get('submission_id', 2)
            return (mock.MagicMock(submission_id=ident), [])

        mock_save.side_effect = raise_on_policy
        params = MultiDict({'policy': 'y', 'policy_id': 'policy_234', 'action': 'next'})
        try:
            policy.policy('POST', params, self.session, 2)
            self.fail('InternalServerError not raised')
        except InternalServerError as e:
            data = e.description
            self.assertIsInstance(data['form'], Form, "Data includes a form")
