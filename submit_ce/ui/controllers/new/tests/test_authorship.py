"""Tests for :mod:`submit_ce.controllers.authorship`."""

from http import HTTPStatus as status

from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError, NotFound
from wtforms import Form

import submit_ce as events
from submit_ce.api.domain.event import ConfirmAuthorship
from submit_ce.ui.controllers.new import authorship


def test_get_request_with_submission(app, mocker, authorized_user_session):
    """GET request with a submission ID."""
    mocker.patch(f'{authorship.__name__}.AuthorshipForm.Meta.csrf', False)
    mock_get = mocker.patch(f'submit_ce.ui.backend.api.get_with_history')
    submission_id = 2
    before = mocker.MagicMock(submission_id=submission_id,
                              submitter_is_author=False)
    mock_get.return_value = (before, [])
    session, _ = authorized_user_session
    with app.test_request_context():
        data, code, _ = authorship.authorship('GET', MultiDict(), session, submission_id)
        assert code == status.OK, "Returns 200 OK"
        assert isinstance(data['form'], Form),  "Data includes a form"

# @mock.patch(f'{authorship.__name__}.AuthorshipForm.Meta.csrf', False)
# #@mock.patch('arxiv.submission.load')
# @mock.patch('submit_ce.ui.routes.ui.api.get')
# def test_get_request_with_nonexistant_submission(self, mock_load):
#     """GET request with a submission ID."""
#     submission_id = 2
#
#     def raise_no_such_submission(*args, **kwargs):
#         raise events.exceptions.NoSuchSubmission('Nada')
#
#     mock_load.side_effect = raise_no_such_submission
#     params = MultiDict()
#
#     with self.assertRaises(NotFound):
#         authorship.authorship('GET', params, self.session, submission_id)
#
# @mock.patch(f'{authorship.__name__}.AuthorshipForm.Meta.csrf', False)
# @mock.patch('submit_ce.ui.routes.ui.api.get')
# def test_post_request(self, mock_load):
#     """POST request with no data."""
#     submission_id = 2
#     before = mock.MagicMock(submission_id=submission_id,
#                             submitter_is_author=False)
#     mock_load.return_value = (before, [])
#     params = MultiDict()
#     _, code, _ = authorship.authorship('POST', params, self.session, submission_id)
#     self.assertEqual(code, status.OK)
#
# @mock.patch(f'{authorship.__name__}.AuthorshipForm.Meta.csrf', False)
# @mock.patch('submit_ce.ui.routes.ui.api.get')
# def test_not_author_no_proxy(self, mock_load):
#     """User indicates they are not author, but also not proxy."""
#     submission_id = 2
#     before = mock.MagicMock(submission_id=submission_id,
#                             submitter_is_author=False)
#     mock_load.return_value = (before, [])
#     params = MultiDict({'authorship': authorship.AuthorshipForm.NO})
#     data, code, _ = authorship.authorship('POST', params, self.session, submission_id)
#     self.assertEqual(code, status.OK)
#
#
# @mock.patch(f'{authorship.__name__}.AuthorshipForm.Meta.csrf', False)
# @mock.patch('submit.controllers.ui.util.url_for')
# @mock.patch(f'{authorship.__name__}.save')
# @mock.patch('submit_ce.ui.routes.ui.api.get')
# def test_post_request_with_data(self, mock_load, mock_save, mock_url_for):
#     """POST request with `authorship` set."""
#     # Event store does not complain; returns object with `submission_id`.
#     submission_id = 2
#     before = mock.MagicMock(submission_id=submission_id,
#                             is_finalized=False,
#                             submitter_is_author=False)
#     after = mock.MagicMock(submission_id=submission_id, is_finalized=False)
#     mock_load.return_value = (before, [])
#     mock_save.return_value = (after, [])
#     mock_url_for.return_value = 'https://foo.bar.com/yes'
#
#     params = MultiDict({'authorship': 'y', 'action': 'next'})
#     _, code, _ = authorship.authorship('POST', params, self.session,
#                                        submission_id)
#     self.assertEqual(code, status.SEE_OTHER, "Returns redirect")
#
# @mock.patch(f'{authorship.__name__}.AuthorshipForm.Meta.csrf', False)
# @mock.patch('submit.controllers.ui.util.url_for')
# @mock.patch(f'{authorship.__name__}.save')
# @mock.patch('submit_ce.ui.routes.ui.api.get')
# def test_save_fails(self, mock_load, mock_save, mock_url_for):
#     """Event store flakes out on saving the command."""
#     submission_id = 2
#     before = mock.MagicMock(submission_id=submission_id,
#                             is_finalized=False,
#                             submitter_is_author=False)
#     mock_load.return_value = (before, [])
#
#     def raise_on_verify(*ev, **kwargs):
#         if type(ev[0]) is ConfirmAuthorship:
#             raise events.SaveError('The world is ending')
#         submission_id = kwargs.get('submission_id', 2)
#         return (mock.MagicMock(submission_id=submission_id), [])
#
#     mock_save.side_effect = raise_on_verify
#     params = MultiDict({'authorship': 'y', 'action': 'next'})
#
#     try:
#         authorship.authorship('POST', params, self.session, 2)
#         self.fail('InternalServerError not raised')
#     except InternalServerError as e:
#         data = e.description
#         self.assertIsInstance(data['form'], Form, "Data includes form")
