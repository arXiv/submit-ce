"""Tests for :mod:`submit_ce.controllers.policy`."""

from datetime import timedelta, datetime
from http import HTTPStatus as status
from unittest import TestCase, mock

from pytz import timezone
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError, NotFound
from wtforms import Form

import submit_ce as events
from submit_ce.ui.domain import ConfirmPolicy
from arxiv.users import auth, domain
from submit_ce.controllers.ui.new import policy

from submit_ce.ui.routes.ui.flow_control import get_controllers_desire, STAGE_SUCCESS

class TestConfirmPolicy(TestCase):
    """Test behavior of :func:`.policy` controller."""

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

    @mock.patch(f'{policy.__name__}.PolicyForm.Meta.csrf', False)
    @mock.patch('arxiv.submission.load')
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
    @mock.patch('arxiv.submission.load')
    def test_get_request_with_nonexistant_submission(self, mock_load):
        """GET request with a submission ID."""
        submission_id = 2

        def raise_no_such_submission(*args, **kwargs):
            raise events.exceptions.NoSuchSubmission('Nada')

        mock_load.side_effect = raise_no_such_submission
        with self.assertRaises(NotFound):
            policy.policy('GET', MultiDict(), self.session,  submission_id)

    @mock.patch(f'{policy.__name__}.PolicyForm.Meta.csrf', False)
    @mock.patch('arxiv.submission.load')
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
    @mock.patch('arxiv.submission.load')
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
    @mock.patch('submit.controllers.ui.util.url_for')
    @mock.patch(f'{policy.__name__}.save')
    @mock.patch('arxiv.submission.load')
    def test_post_request_with_data(self, mock_load, mock_save, mock_url_for):
        """POST request with `policy` set."""
        # Event store does not complain; returns object with `submission_id`.
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False,
                                submitter_accepts_policy=False)
        after = mock.MagicMock(submission_id=submission_id, is_finalized=False)
        mock_load.return_value = (before, [])
        mock_save.return_value = (after, [])
        mock_url_for.return_value = 'https://foo.bar.com/yes'

        params = MultiDict({'policy': 'y', 'action': 'next'})
        data, code, _ = policy.policy('POST', params, self.session, submission_id)
        self.assertEqual(code, status.OK)
        self.assertEqual(get_controllers_desire(data), STAGE_SUCCESS)


    @mock.patch(f'{policy.__name__}.PolicyForm.Meta.csrf', False)
    @mock.patch('submit.controllers.ui.util.url_for')
    @mock.patch(f'{policy.__name__}.save')
    @mock.patch('arxiv.submission.load')
    def test_post_request_with_data_already_accepted(self, mock_load, mock_save, mock_url_for):
        """POST request with `policy` y and already set on the submission."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False,
                                submitter_accepts_policy=True)
        after = mock.MagicMock(submission_id=submission_id, is_finalized=False)
        mock_load.return_value = (before, [])
        mock_save.return_value = (after, [])
        mock_url_for.return_value = 'https://foo.bar.com/yes'

        params = MultiDict({'policy': 'y', 'action': 'next'})
        data, code, _ = policy.policy('POST', params, self.session, submission_id)
        self.assertEqual(code, status.OK)
        self.assertEqual(get_controllers_desire(data), STAGE_SUCCESS)
        
    @mock.patch(f'{policy.__name__}.PolicyForm.Meta.csrf', False)
    @mock.patch('submit.controllers.ui.util.url_for')
    @mock.patch(f'{policy.__name__}.save')
    @mock.patch('arxiv.submission.load')
    def test_save_fails(self, mock_load, mock_save, mock_url_for):
        """Event store flakes out on saving policy acceptance."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id,
                                is_finalized=False,
                                submitter_accepts_policy=False)
        mock_load.return_value = (before, [])

        # Event store does not complain; returns object with `submission_id`
        def raise_on_policy(*ev, **kwargs):
            if type(ev[0]) is ConfirmPolicy:
                raise events.SaveError('the end of the world as we know it')
            ident = kwargs.get('submission_id', 2)
            return (mock.MagicMock(submission_id=ident), [])

        mock_save.side_effect = raise_on_policy
        params = MultiDict({'policy': 'y', 'action': 'next'})
        try:
            policy.policy('POST', params, self.session, 2)
            self.fail('InternalServerError not raised')
        except InternalServerError as e:
            data = e.description
            self.assertIsInstance(data['form'], Form, "Data includes a form")
