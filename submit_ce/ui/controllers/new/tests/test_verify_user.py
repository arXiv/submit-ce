"""Tests for :mod:`submit_ce.controllers.verify_user`."""

from unittest import TestCase, mock
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError
from wtforms import Form
from http import HTTPStatus as status
import submit_ce as events
from submit_ce.api.domain.event import ConfirmContactInformation
from submit_ce.api.exceptions import SaveError
from submit_ce.ui.controllers.new import verify_user

from pytz import timezone
from datetime import timedelta, datetime
from arxiv.auth import auth, domain

import submit_ce.api.domain
from submit_ce.ui.tests import CtrlBase


class TestVerifyUser(CtrlBase):
    """Test behavior of :func:`.verify_user` controller."""

    @mock.patch(f'{verify_user.__name__}.VerifyUserForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_get_request_with_submission(self, mock_load):
        """GET request with a submission ID."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False,
                                submitter_contact_verified=False)
        mock_load.return_value = (before, [])
        data, code, _ = verify_user.verify('GET', MultiDict(), self.session,
                                           submission_id)
        self.assertEqual(code, status.OK, "Returns 200 OK")
        self.assertIsInstance(data['form'], Form, "Data includes a form")

    @mock.patch(f'{verify_user.__name__}.VerifyUserForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_post_request(self, mock_load):
        """POST request with no data."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False,
                                submitter_contact_verified=False)
        mock_load.return_value = (before, [])
        params = MultiDict()
        data, code, _ = verify_user.verify('POST', params, self.session,
                                           submission_id)
        self.assertEqual(code, status.OK)
        self.assertIsInstance(data['form'], Form, "Data includes a form")

    @mock.patch(f'{verify_user.__name__}.VerifyUserForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.backend.api.save')
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_post_request_with_data(self, mock_load, mock_save):
        """POST request with `verify_user` set."""
        # Event store does not complain; returns object with `submission_id`.
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False,
                                submitter_contact_verified=False)
        after = mock.MagicMock(submission_id=submission_id, is_finalized=False,
                               submitter_contact_verified=True)
        mock_load.return_value = (before, [])
        mock_save.return_value = (after, [])

        form_data = MultiDict({'verify_user': 'y', 'action': 'next'})
        _, code, _ = verify_user.verify('POST', form_data, self.session,
                                        submission_id)
        self.assertEqual(code, status.OK,)

    @mock.patch(f'{verify_user.__name__}.VerifyUserForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.backend.api.save')
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_save_fails(self, mock_load, mock_save):
        """Event store flakes out saving authorship verification."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False,
                                submitter_contact_verified=False)
        mock_load.return_value = (before, [])

        # Event store does not complain; returns object with `submission_id`
        def raise_on_verify(*ev, **kwargs):
            raise SaveError('not today')
            # ident = kwargs.get('submission_id', 2)
            # return (mock.MagicMock(submission_id=ident,
            #                        submitter_contact_verified=False), [])

        mock_save.side_effect = raise_on_verify
        params = MultiDict({'verify_user': 'y', 'action': 'next'})
        try:
            verify_user.verify('POST', params, self.session, 2)
            self.fail('InternalServerError not raised')
        except InternalServerError as e:
            data = e.description
            self.assertIsInstance(data['form'], Form, "Data includes a form")
