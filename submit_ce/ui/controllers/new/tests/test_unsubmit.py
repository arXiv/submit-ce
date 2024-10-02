"""Tests for :mod:`submit_ce.controllers.unsubmit`."""

from unittest import TestCase, mock
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import BadRequest
from wtforms import Form
from http import HTTPStatus as status
from submit_ce.ui.controllers.new import unsubmit

from pytz import timezone
from datetime import timedelta, datetime
from arxiv.users import auth, domain


class TestUnsubmit(TestCase):
    """Test behavior of :func:`.unsubmit` controller."""

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
                name=domain.UserFullName("Jane", "Bloggs", "III"),
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

    @mock.patch(f'{unsubmit.__name__}.UnsubmitForm.Meta.csrf', False)
    @mock.patch('arxiv.submission.load')
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

    @mock.patch(f'{unsubmit.__name__}.UnsubmitForm.Meta.csrf', False)
    @mock.patch('arxiv.submission.load')
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

    @mock.patch(f'{unsubmit.__name__}.UnsubmitForm.Meta.csrf', False)
    @mock.patch(f'{unsubmit.__name__}.url_for')
    @mock.patch('arxiv.base.alerts.flash_success')
    @mock.patch(f'{unsubmit.__name__}.save')
    @mock.patch('arxiv.submission.load')
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
