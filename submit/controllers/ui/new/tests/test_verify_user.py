"""Tests for :mod:`submit.controllers.verify_user`."""

from unittest import TestCase, mock
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError, BadRequest
from wtforms import Form
from http import HTTPStatus as status
import arxiv.submission as events
from arxiv.submission.domain.event import ConfirmContactInformation
from submit.controllers.ui.new import verify_user

from pytz import timezone
from datetime import timedelta, datetime
from arxiv_auth import auth, domain


class TestVerifyUser(TestCase):
    """Test behavior of :func:`.verify_user` controller."""

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

    @mock.patch(f'{verify_user.__name__}.VerifyUserForm.Meta.csrf', False)
    @mock.patch('arxiv.submission.load')
    def test_get_request_with_submission(self, mock_load):
        """GET request with a ui-app ID."""
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
    @mock.patch('arxiv.submission.load')
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
    @mock.patch('submit.controllers.ui.util.url_for')
    @mock.patch(f'{verify_user.__name__}.save')
    @mock.patch('arxiv.submission.load')
    def test_post_request_with_data(self, mock_load, mock_save, mock_url_for):
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
        mock_url_for.return_value = 'https://foo.bar.com/yes'

        form_data = MultiDict({'verify_user': 'y', 'action': 'next'})
        _, code, _ = verify_user.verify('POST', form_data, self.session,
                                        submission_id)
        self.assertEqual(code, status.OK,)

    @mock.patch(f'{verify_user.__name__}.VerifyUserForm.Meta.csrf', False)
    @mock.patch('submit.controllers.ui.util.url_for')
    @mock.patch(f'{verify_user.__name__}.save')
    @mock.patch('arxiv.submission.load')
    def test_save_fails(self, mock_load, mock_save, mock_url_for):
        """Event store flakes out saving authorship verification."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False,
                                submitter_contact_verified=False)
        mock_load.return_value = (before, [])

        # Event store does not complain; returns object with `submission_id`
        def raise_on_verify(*ev, **kwargs):
            if type(ev[0]) is ConfirmContactInformation:
                raise events.SaveError('not today')
            ident = kwargs.get('submission_id', 2)
            return (mock.MagicMock(submission_id=ident,
                                   submitter_contact_verified=False), [])

        mock_save.side_effect = raise_on_verify
        params = MultiDict({'verify_user': 'y', 'action': 'next'})
        try:
            verify_user.verify('POST', params, self.session, 2)
            self.fail('InternalServerError not raised')
        except InternalServerError as e:
            data = e.description
            self.assertIsInstance(data['form'], Form, "Data includes a form")
