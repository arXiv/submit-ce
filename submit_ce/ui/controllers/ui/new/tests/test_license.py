"""Tests for :mod:`submit_ce.controllers.license`."""

from datetime import timedelta, datetime
from http import HTTPStatus as status
from unittest import TestCase, mock

from pytz import timezone
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError, NotFound
from wtforms import Form

import submit_ce as events
from submit_ce.ui.domain import SetLicense
from arxiv.users import auth, domain

from submit_ce.controllers.ui.new import license

from submit_ce.ui.routes.ui.flow_control import get_controllers_desire, STAGE_SUCCESS

class TestSetLicense(TestCase):
    """Test behavior of :func:`.license` controller."""

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

    @mock.patch(f'{license.__name__}.LicenseForm.Meta.csrf', False)
    @mock.patch('arxiv.submission.load')
    def test_get_request_with_submission(self, mock_load):
        """GET request with a submission ID."""
        submission_id = 2
        mock_load.return_value = (
            mock.MagicMock(submission_id=submission_id), []
        )
        rdata, code, _ = license.license('GET', MultiDict(), self.session,
                                         submission_id)
        self.assertEqual(code, status.OK, "Returns 200 OK")
        self.assertIsInstance(rdata['form'], Form, "Data includes a form")

    @mock.patch(f'{license.__name__}.LicenseForm.Meta.csrf', False)
    @mock.patch('arxiv.submission.load')
    def test_get_request_with_nonexistant_submission(self, mock_load):
        """GET request with a submission ID."""
        submission_id = 2

        def raise_no_such_submission(*args, **kwargs):
            raise events.exceptions.NoSuchSubmission('Nada')

        mock_load.side_effect = raise_no_such_submission
        with self.assertRaises(NotFound):
            license.license('GET', MultiDict(), self.session, submission_id)

    @mock.patch(f'{license.__name__}.LicenseForm.Meta.csrf', False)
    @mock.patch('arxiv.submission.load')
    def test_post_request(self, mock_load):
        """POST request with no data."""
        submission_id = 2
        mock_load.return_value = (
            mock.MagicMock(submission_id=submission_id), []
        )
        data, _, _ = license.license('POST', MultiDict(), self.session, submission_id)
        self.assertIsInstance(data['form'], Form, "Data includes a form")

    @mock.patch(f'{license.__name__}.LicenseForm.Meta.csrf', False)
    @mock.patch('submit.controllers.ui.util.url_for')
    @mock.patch(f'{license.__name__}.save')
    @mock.patch('arxiv.submission.load')
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


    @mock.patch(f'{license.__name__}.LicenseForm.Meta.csrf', False)
    @mock.patch('submit.controllers.ui.util.url_for')
    @mock.patch(f'{license.__name__}.save')
    @mock.patch('arxiv.submission.load')
    def test_post_request_with_data(self, mock_load, mock_save, mock_url_for):
        """POST request with `license` set and same license already on submission."""
        submission_id = 2
        arxiv_lic = 'http://arxiv.org/licenses/nonexclusive-distrib/1.0/'
        lic = mock.MagicMock(uri=arxiv_lic)
        sub = mock.MagicMock(submission_id=submission_id,
                             license=lic,
                             is_finalized=False)
        mock_load.return_value = (sub, [])
        mock_save.return_value = (sub, [])
        mock_url_for.return_value = 'https://example.com/'

        form_data = MultiDict({
            'license': arxiv_lic,
            'action': 'next'
        })
        data, code, headers = license.license('POST', form_data, self.session,
                                              submission_id)
        self.assertEqual(get_controllers_desire(data), STAGE_SUCCESS)

    @mock.patch(f'{license.__name__}.LicenseForm.Meta.csrf', False)
    @mock.patch('submit.controllers.ui.util.url_for')
    @mock.patch(f'{license.__name__}.save')
    @mock.patch('arxiv.submission.load')
    def test_save_fails(self, mock_load, mock_save, mock_url_for):
        """Event store flakes out on saving license selection."""
        submission_id = 2
        sub = mock.MagicMock(submission_id=submission_id, is_finalized=False)
        mock_load.return_value = (sub, [])

        # Event store does not complain; returns object with `submission_id`
        def raise_on_verify(*ev, **kwargs):
            if type(ev[0]) is SetLicense:
                raise events.SaveError('the sky is falling')
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
