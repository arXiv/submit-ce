"""Tests for :mod:`submit.controllers.authorship`."""

from datetime import timedelta, datetime
from http import HTTPStatus as status
from unittest import TestCase, mock

from arxiv_auth import domain, auth
from pytz import timezone
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError, NotFound, BadRequest
from wtforms import Form

import arxiv.submission as events
from arxiv.submission.domain.event import ConfirmAuthorship

from submit.controllers.ui.new import authorship
from submit.routes.ui.flow_control import get_controllers_desire, STAGE_RESHOW

class TestVerifyAuthorship(TestCase):
    """Test behavior of :func:`.authorship` controller."""

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

    @mock.patch(f'{authorship.__name__}.AuthorshipForm.Meta.csrf', False)
    @mock.patch('arxiv.submission.load')
    def test_get_request_with_submission(self, mock_load):
        """GET request with a ui-app ID."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                submitter_is_author=False)
        mock_load.return_value = (before, [])
        data, code, _ = authorship.authorship('GET', MultiDict(), self.session,
                                              submission_id)
        self.assertEqual(code, status.OK, "Returns 200 OK")
        self.assertIsInstance(data['form'], Form, "Data includes a form")

    @mock.patch(f'{authorship.__name__}.AuthorshipForm.Meta.csrf', False)
    @mock.patch('arxiv.submission.load')
    def test_get_request_with_nonexistant_submission(self, mock_load):
        """GET request with a ui-app ID."""
        submission_id = 2

        def raise_no_such_submission(*args, **kwargs):
            raise events.exceptions.NoSuchSubmission('Nada')

        mock_load.side_effect = raise_no_such_submission
        params = MultiDict()

        with self.assertRaises(NotFound):
            authorship.authorship('GET', params, self.session, submission_id)

    @mock.patch(f'{authorship.__name__}.AuthorshipForm.Meta.csrf', False)
    @mock.patch('arxiv.submission.load')
    def test_post_request(self, mock_load):
        """POST request with no data."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                submitter_is_author=False)
        mock_load.return_value = (before, [])
        params = MultiDict()
        _, code, _ = authorship.authorship('POST', params, self.session, submission_id)
        self.assertEqual(code, status.OK)

    @mock.patch(f'{authorship.__name__}.AuthorshipForm.Meta.csrf', False)
    @mock.patch('arxiv.submission.load')
    def test_not_author_no_proxy(self, mock_load):
        """User indicates they are not author, but also not proxy."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                submitter_is_author=False)
        mock_load.return_value = (before, [])
        params = MultiDict({'authorship': authorship.AuthorshipForm.NO})
        data, code, _ = authorship.authorship('POST', params, self.session, submission_id)        
        self.assertEqual(code, status.OK)


    @mock.patch(f'{authorship.__name__}.AuthorshipForm.Meta.csrf', False)
    @mock.patch('submit.controllers.ui.util.url_for')
    @mock.patch(f'{authorship.__name__}.save')
    @mock.patch('arxiv.submission.load')
    def test_post_request_with_data(self, mock_load, mock_save, mock_url_for):
        """POST request with `authorship` set."""
        # Event store does not complain; returns object with `submission_id`.
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False,
                                submitter_is_author=False)
        after = mock.MagicMock(submission_id=submission_id, is_finalized=False)
        mock_load.return_value = (before, [])
        mock_save.return_value = (after, [])
        mock_url_for.return_value = 'https://foo.bar.com/yes'

        params = MultiDict({'authorship': 'y', 'action': 'next'})
        _, code, _ = authorship.authorship('POST', params, self.session,
                                           submission_id)
        self.assertEqual(code, status.SEE_OTHER, "Returns redirect")

    @mock.patch(f'{authorship.__name__}.AuthorshipForm.Meta.csrf', False)
    @mock.patch('submit.controllers.ui.util.url_for')
    @mock.patch(f'{authorship.__name__}.save')
    @mock.patch('arxiv.submission.load')
    def test_save_fails(self, mock_load, mock_save, mock_url_for):
        """Event store flakes out on saving the command."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False,
                                submitter_is_author=False)
        mock_load.return_value = (before, [])

        def raise_on_verify(*ev, **kwargs):
            if type(ev[0]) is ConfirmAuthorship:
                raise events.SaveError('The world is ending')
            submission_id = kwargs.get('submission_id', 2)
            return (mock.MagicMock(submission_id=submission_id), [])

        mock_save.side_effect = raise_on_verify
        params = MultiDict({'authorship': 'y', 'action': 'next'})

        try:
            authorship.authorship('POST', params, self.session, 2)
            self.fail('InternalServerError not raised')
        except InternalServerError as e:
            data = e.description
            self.assertIsInstance(data['form'], Form, "Data includes form")
