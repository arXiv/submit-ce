"""Tests for :mod:`submit_ce.controllers.classification`."""

from unittest import TestCase, mock

from arxiv.auth import auth, domain
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import NotFound
from wtforms import Form
from http import HTTPStatus as status
import submit_ce as events

from pytz import timezone
from datetime import timedelta, datetime

import submit_ce.api.domain
from submit_ce.api.exceptions import NoSuchSubmission
from submit_ce.ui.controllers.new import classification
from submit_ce.ui.routes.flow_control import STAGE_CURRENT, STAGE_RESHOW, get_controllers_desire
from submit_ce.ui.tests import CtrlBase

class TestClassification(CtrlBase):
    """Test behavior of :func:`.classification` controller."""


    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.controllers.new.classification.get_submission')
    def test_get_request_with_submission(self, mock_load):
        """GET request with a submission ID."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False, is_announced=False, version=1, arxiv_id=None)
        mock_load.return_value = (before, [])
        data, code, _ = classification.classification('GET', MultiDict(),
                                                   self.session,
                                                   submission_id)
        self.assertIsInstance(data['form'], Form, "Data includes a form")
        self.assertEqual(code, status.OK)

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.controllers.new.classification.get_submission')
    def test_get_request_with_nonexistant_submission(self, mock_load):
        """GET request with a submission ID."""
        submission_id = 2
        def raise_no_such_submission(*args, **kwargs):
            raise NotFound('Nada')

        mock_load.side_effect = raise_no_such_submission
        with self.assertRaises(NotFound):
            classification.classification('GET', MultiDict(), self.session, submission_id)

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.controllers.new.classification.get_submission')
    def test_post_request(self, mock_load):
        """POST request with no data."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False, is_announced=False, version=1, arxiv_id=None)
        mock_load.return_value = (before, [])
        data, code, _ = classification.classification('POST', MultiDict(), self.session, submission_id)
        self.assertIsInstance(data['form'], Form, "Data includes a form")
        self.assertEqual(code, status.BAD_REQUEST, "no data should do 400")

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.auth.get_endorsements')
    @mock.patch(f'{classification.__name__}.api.save')
    @mock.patch('submit_ce.ui.controllers.new.classification.get_submission')
    def test_post_with_already_set_category(self, mock_load, mock_save, mock_endo):
        """POST request with valid category."""
        submission_id = 2
        mock_endo.return_value = self.user.endorsements
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False, is_announced=False, version=1, arxiv_id=None)
        mock_clsn = mock.MagicMock(category='astro-ph.CO')
        after = mock.MagicMock(submission_id=submission_id,
                               is_finalized=False, primary_classification=mock_clsn,
                               is_announced=False, version=1, arxiv_id=None)
        mock_load.return_value = (before, [])
        mock_save.return_value = (after, [])
        params = MultiDict({'category': 'astro-ph.CO'})
        data, code, _ = classification.classification('POST', params, self.session, submission_id)


class TestCrossList(CtrlBase):
    """Test behavior of :func:`.cross_list` controller."""

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.auth.get_endorsements')
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_get_request_with_submission(self, mock_load, mock_endo):
        """GET request with a submission ID."""
        submission_id = 2
        mock_endo.return_value = ['astro-ph.EP']+self.user.endorsements
        mock_clsn = mock.MagicMock(category='astro-ph.EP')
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False,
                                primary_classification=mock_clsn,
                                is_announced=False, version=1, arxiv_id=None)
        mock_load.return_value = (before, [])
        params = MultiDict()
        data, code, _ = classification.cross_list('GET', params, self.session, submission_id)
        self.assertEqual(code, status.OK, "Returns 200 OK")
        self.assertIsInstance(data['form'], Form, "Data includes a form")

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.auth.get_endorsements')
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
    def test_get_request_with_nonexistant_submission(self, mock_load, mock_endo):
        """GET request with a submission ID."""
        submission_id = 2
        mock_endo.return_value = ['astro-ph.EP']+self.user.endorsements
        def raise_no_such_submission(*args, **kwargs):
            raise NoSuchSubmission('Nada')

        mock_load.side_effect = raise_no_such_submission
        with self.assertRaises(NoSuchSubmission):
            classification.cross_list('GET', MultiDict(), self.session, submission_id)

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf', False)
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
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

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf', False)
    @mock.patch(f'submit_ce.ui.backend.api.save')
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
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
        data, code, _ = classification.classification('POST', params, self.session,
                                                   submission_id)        
        self.assertIsInstance(data['form'], Form, "Data includes a form")
        self.assertEqual(code, status.BAD_REQUEST, "bad data should do 400")

    @mock.patch(f'{classification.__name__}.ClassificationForm.Meta.csrf', False)
    @mock.patch(f'submit_ce.ui.backend.api.save')
    @mock.patch('submit_ce.ui.backend.api.get_with_history')
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
