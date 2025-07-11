"""Tests for :mod:`submit_ce.controllers.classification`."""

from http import HTTPStatus as status
from unittest import mock

from arxiv.auth.domain import Session
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError, NotFound
from wtforms import Form

from submit_ce.api.domain.agent import InternalClient
from submit_ce.api.exceptions import NoSuchSubmission, SaveError
from submit_ce.ui.controllers.new import classification

from submit_ce.ui.tests import CtrlBase
from submit_ce.ui.routes.flow_control import get_controllers_desire, STAGE_SUCCESS


ua = InternalClient(name=f"test_client_{__file__}")

class TestSetPrimaryClassification(CtrlBase):
    """Test behavior of :func:`.classification` controller."""

    def setUp(self) -> None:
        super().setUp()
        self.user.endorsements.append("cs.CV")

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.controllers.new.classification.user_and_client_from_session')
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_get_request_with_submission(self, mock_load, mock_user_client):
        """GET request with a submission ID."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_announced=False,
                                arxiv_id=None, submitter_is_author=False,
                                is_finalized=False, version=1)
        mock_load.return_value = (before, [])
        mock_user_client.return_value = (self.user, ua)
        params = MultiDict()
        data, code, _ = classification.classification('GET', params,
                                                      self.session,
                                                      submission_id)
        self.assertEqual(code, status.OK, "Returns 200 OK")
        self.assertIsInstance(data['form'], Form, "Data includes a form")

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_get_request_with_nonexistant_submission(self, mock_load):
        """GET request with a submission ID."""
        submission_id = 2

        def raise_no_such_submission(*args, **kwargs):
            raise NoSuchSubmission('Nada')

        mock_load.side_effect = raise_no_such_submission
        with self.assertRaises(NoSuchSubmission):
            classification.classification('GET', MultiDict(), self.session,
                                          submission_id)

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_post_request(self, mock_load):
        """POST request with no data."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_announced=False,
                                arxiv_id=None, submitter_is_author=False,
                                is_finalized=False, version=1)
        mock_load.return_value = (before, [])
        data, code, _  = classification.classification('POST', MultiDict(), self.session,
                                                    submission_id)
        self.assertIsInstance(data['form'], Form, "Data includes a form")
        self.assertNotEqual(get_controllers_desire(data), STAGE_SUCCESS)


    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.controllers.new.classification.user_and_client_from_session')
    @mock.patch('submit_ce.ui.backend.api.save')
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_post_request_with_data(self, mock_load, mock_save, mock_user_client ):
        """POST request with `classification` set."""
        # Event store does not complain; returns object with `submission_id`.
        submission_id = 2
        mock_user_client.return_value = (self.user, ua)
        before = mock.MagicMock(submission_id=submission_id,
                                is_announced=False,
                                arxiv_id=None, submitter_is_author=False,
                                is_finalized=False, version=1)
        mock_clsn = mock.MagicMock(category='astro-ph.CO')
        after = mock.MagicMock(submission_id=submission_id, is_announced=False,
                               arxiv_id=None, submitter_is_author=False,
                               primary_classification=mock_clsn,
                               is_finalized=False, version=1)
        mock_load.return_value = (before, [])
        mock_save.return_value = (after, [])

        params = MultiDict({'category': 'cs.CV', 'operation': 'add', 'action': 'next'})
        data, code, _ = classification.classification('POST', params, self.session, submission_id)
        self.assertEqual(get_controllers_desire(data), STAGE_SUCCESS)


    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.controllers.new.classification.user_and_client_from_session')
    @mock.patch('submit_ce.ui.backend.api.save')
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_post_request_with_unendorsed_data(self, mock_load, mock_save, mock_user_client ):
        """POST request with bad `classification` set."""
        submission_id = 2
        mock_user_client.return_value = (self.user, ua)
        before = mock.MagicMock(submission_id=submission_id,
                                is_announced=False,
                                arxiv_id=None, submitter_is_author=False,
                                is_finalized=False, version=1)
        mock_clsn = mock.MagicMock(category='astro-ph.CO')
        after = mock.MagicMock(submission_id=submission_id, is_announced=False,
                               arxiv_id=None, submitter_is_author=False,
                               primary_classification=mock_clsn,
                               is_finalized=False, version=1)
        mock_load.return_value = (before, [])
        mock_save.return_value = (after, [])

        params = MultiDict({'category': 'math.DS', 'operation': 'add', 'action': 'next'})
        data, _, _ = classification.classification('POST', params, self.session, submission_id)
        self.assertNotEqual(get_controllers_desire(data), STAGE_SUCCESS)


    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.controllers.new.classification.user_and_client_from_session')
    @mock.patch('submit_ce.ui.backend.api.save')
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_save_error(self, mock_load, mock_save, mock_user_client):
        """Event store flakes out on saving classification event."""
        mock_user_client.return_value = (self.user, ua)
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_announced=False,
                                arxiv_id=None, submitter_is_author=False,
                                is_finalized=False, version=1)
        mock_load.return_value = (before, [])
        def raise_on_set(*ev, **kwargs):
            raise SaveError('never get back')
        mock_save.side_effect = raise_on_set

        params = MultiDict({'category': 'cs.CV', 'action': 'next'})
        try:
            classification.classification('POST', params, self.session, 2)
            self.fail('InternalServerError not raised')
        except InternalServerError as e:
            data = e.description
            self.assertIsInstance(data['form'], Form, "Data includes a form")
