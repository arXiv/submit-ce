"""Tests for :mod:`submit_ce.controllers.metadata`."""

from datetime import timedelta, datetime
from http import HTTPStatus as status
from unittest import TestCase, mock

from pytz import timezone
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError
from wtforms import Form

import submit_ce as events
from submit_ce.ui.domain import SetTitle, SetAbstract, SetAuthors, \
    SetReportNumber, SetMSCClassification, SetACMClassification, SetDOI, \
    SetJournalReference
from arxiv.users import auth, domain

from submit_ce.controllers.ui.new import metadata


class TestOptional(TestCase):
    """Tests for :func:`.optional`."""

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

    @mock.patch(f'{metadata.__name__}.OptionalMetadataForm.Meta.csrf', False)
    @mock.patch('arxiv.submission.load')
    def test_get_request_with_submission(self, mock_load):
        """GET request with a submission ID."""
        submission_id = 2
        mock_load.return_value = (
            mock.MagicMock(submission_id=submission_id), []
        )
        data, code, headers = metadata.optional(
            'GET', MultiDict(), self.session, submission_id)
        self.assertEqual(code, status.OK, "Returns 200 OK")
        self.assertIsInstance(data['form'], Form,
                              "Response data includes a form")

    @mock.patch(f'{metadata.__name__}.OptionalMetadataForm.Meta.csrf', False)
    @mock.patch('arxiv.submission.load')
    def test_post_request_with_no_data(self, mock_load):
        """POST request has no form data."""
        submission_id = 2
        mock_load.return_value = (
            mock.MagicMock(submission_id=submission_id), []
        )
        data, code, headers = metadata.optional(
            'POST', MultiDict(), self.session, submission_id)
        self.assertEqual(code, status.OK, "Returns 200 OK")

        self.assertIsInstance(data['form'], Form,
                              "Response data includes a form")

    @mock.patch(f'{metadata.__name__}.OptionalMetadataForm.Meta.csrf', False)
    @mock.patch(f'{metadata.__name__}.save')
    @mock.patch('arxiv.submission.load')
    def test_save_error_is_raised(self, mock_load, mock_save):
        """POST request results in an SaveError exception."""
        submission_id = 2
        mock_submission = mock.MagicMock(
            submission_id=submission_id,
            is_finalized=False,
            metadata=mock.MagicMock()
        )
        mock_load.return_value = (mock_submission, [])

        def raise_save_error(*args, **kwargs):
            raise events.SaveError('nope')

        mock_save.side_effect = raise_save_error
        params = MultiDict({
            'doi': '10.0001/123456',
            'journal_ref': 'foo journal 10 2010: 12-345',
            'report_num': 'foo report 12',
            'acm_class': 'F.2.2; I.2.7',
            'msc_class': '14J26'
        })
        with self.assertRaises(InternalServerError):
            metadata.optional('POST', params, self.session, submission_id)

    @mock.patch(f'{metadata.__name__}.OptionalMetadataForm.Meta.csrf', False)
    @mock.patch(f'{metadata.__name__}.save')
    @mock.patch('arxiv.submission.load')
    def test_post_request_with_required_data(self, mock_load, mock_save):
        """POST request with all fields."""
        submission_id = 2
        mock_submission = mock.MagicMock(submission_id=submission_id,
                                         is_finalized=False,
                                         metadata=mock.MagicMock())
        mock_load.return_value = (mock_submission, [])
        mock_save.return_value = (mock_submission, [])
        params = MultiDict({
            'doi': '10.0001/123456',
            'journal_ref': 'foo journal 10 2010: 12-345',
            'report_num': 'foo report 12',
            'acm_class': 'F.2.2; I.2.7',
            'msc_class': '14J26'
        })
        data, code, headers = metadata.optional('POST', params, self.session,
                                                submission_id)
        self.assertEqual(code, status.OK, "Returns 200 OK")
        event_types = [type(ev) for ev in mock_save.call_args[0]]
        self.assertIn(SetDOI, event_types, "Sets submission DOI")
        self.assertIn(SetJournalReference, event_types,
                      "Sets journal references")
        self.assertIn(SetReportNumber, event_types,
                      "Sets report number")
        self.assertIn(SetACMClassification, event_types,
                      "Sets ACM classification")
        self.assertIn(SetMSCClassification, event_types,
                      "Sets MSC classification")

    @mock.patch(f'{metadata.__name__}.OptionalMetadataForm.Meta.csrf', False)
    @mock.patch(f'{metadata.__name__}.save')
    @mock.patch('arxiv.submission.load')
    def test_post_request_with_unchanged_data(self, mock_load, mock_save):
        """POST request with valid but unchanged data."""
        submission_id = 2
        mock_submission = mock.MagicMock(
            submission_id=submission_id,
            is_finalized=False,
            metadata=mock.MagicMock(**{
                'doi': '10.0001/123456',
                'journal_ref': 'foo journal 10 2010: 12-345',
                'report_num': 'foo report 12',
                'acm_class': 'F.2.2; I.2.7',
                'msc_class': '14J26'
            })
        )
        mock_load.return_value = (mock_submission, [])
        mock_save.return_value = (mock_submission, [])
        params = MultiDict({
            'doi': '10.0001/123456',
            'journal_ref': 'foo journal 10 2010: 12-345',
            'report_num': 'foo report 12',
            'acm_class': 'F.2.2; I.2.7',
            'msc_class': '14J26'
        })
        _, code, _ = metadata.optional('POST', params, self.session,
                                       submission_id)
        self.assertEqual(code, status.OK, "Returns 200 OK")
        self.assertEqual(mock_save.call_count, 0, "No events are generated")

    @mock.patch(f'{metadata.__name__}.OptionalMetadataForm.Meta.csrf', False)
    @mock.patch(f'{metadata.__name__}.save')
    @mock.patch('arxiv.submission.load')
    def test_post_request_with_some_changes(self, mock_load, mock_save):
        """POST request with only some changed data."""
        submission_id = 2
        mock_submission = mock.MagicMock(
            submission_id=submission_id,
            is_finalized=False,
            metadata=mock.MagicMock(**{
                'doi': '10.0001/123456',
                'journal_ref': 'foo journal 10 2010: 12-345',
                'report_num': 'foo report 12',
                'acm_class': 'F.2.2; I.2.7',
                'msc_class': '14J26'
            })
        )
        mock_load.return_value = (mock_submission, [])
        mock_save.return_value = (mock_submission, [])
        params = MultiDict({
            'doi': '10.0001/123456',
            'journal_ref': 'foo journal 10 2010: 12-345',
            'report_num': 'foo report 13',
            'acm_class': 'F.2.2; I.2.7',
            'msc_class': '14J27'
        })
        _, code, _ = metadata.optional('POST', params, self.session,
                                       submission_id)
        self.assertEqual(code, status.OK, "Returns 200 OK")
        self.assertEqual(mock_save.call_count, 1, "Events are generated")

        event_types = [type(ev) for ev in mock_save.call_args[0]]
        self.assertIn(SetReportNumber, event_types, "Sets report_num")
        self.assertIn(SetMSCClassification, event_types, "Sets msc")
        self.assertEqual(len(event_types), 2, "Only two events are generated")


class TestMetadata(TestCase):
    """Tests for :func:`.metadata`."""

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

    @mock.patch(f'{metadata.__name__}.CoreMetadataForm.Meta.csrf', False)
    @mock.patch('arxiv.submission.load')
    def test_get_request_with_submission(self, mock_load):
        """GET request with a submission ID."""
        submission_id = 2
        before = mock.MagicMock(submission_id=submission_id)
        mock_load.return_value = (before, [])
        data, code, _ = metadata.metadata('GET', MultiDict(), self.session,
                                          submission_id)
        self.assertEqual(code, status.OK, "Returns 200 OK")
        self.assertIsInstance(data['form'], Form, "Data includes a form")

    @mock.patch(f'{metadata.__name__}.CoreMetadataForm.Meta.csrf', False)
    @mock.patch('arxiv.submission.load')
    def test_post_request_with_no_data(self, mock_load):
        """POST request has no form data."""
        submission_id = 2
        mock_load.return_value = (
            mock.MagicMock(submission_id=submission_id), []
        )
        data, _, _ = metadata.metadata('POST', MultiDict(), self.session, submission_id)        
        self.assertIsInstance(data['form'], Form, "Data includes a form")

    @mock.patch(f'{metadata.__name__}.CoreMetadataForm.Meta.csrf', False)
    @mock.patch(f'{metadata.__name__}.save')
    @mock.patch('arxiv.submission.load')
    def test_post_request_with_required_data(self, mock_load, mock_save):
        """POST request with title, abstract, and author names."""
        submission_id = 2
        mock_submission = mock.MagicMock(
            submission_id=submission_id,
            is_finalized=False,
            metadata=mock.MagicMock(
                title='the old title',
                abstract='not the abstract that you are looking for',
                authors_display='bloggs, j'
            )
        )
        mock_load.return_value = (mock_submission, [])
        mock_save.return_value = (mock_submission, [])
        params = MultiDict({
            'title': 'a new, valid title',
            'abstract': 'this abstract is at least twenty characters long',
            'authors_display': 'j doe, j bloggs'
        })
        _, code, _ = metadata.metadata('POST', params, self.session,
                                       submission_id)
        self.assertEqual(code, status.OK, "Returns 200 OK")

        event_types = [type(ev) for ev in mock_save.call_args[0]]
        self.assertIn(SetTitle, event_types, "Sets submission title")
        self.assertIn(SetAbstract, event_types, "Sets abstract")
        self.assertIn(SetAuthors, event_types, "Sets authors")

    @mock.patch(f'{metadata.__name__}.CoreMetadataForm.Meta.csrf', False)
    @mock.patch(f'{metadata.__name__}.save')
    @mock.patch('arxiv.submission.load')
    def test_post_request_with_unchanged_data(self, mock_load, mock_save):
        """POST request with valid but unaltered data."""
        submission_id = 2
        mock_submission = mock.MagicMock(
            submission_id=submission_id,
            is_finalized=False,
            metadata=mock.MagicMock(
                title='the old title',
                abstract='not the abstract that you are looking for',
                authors_display='bloggs, j'
            )
        )
        mock_load.return_value = (mock_submission, [])
        mock_save.return_value = (mock_submission, [])
        params = MultiDict({
            'title': 'the old title',
            'abstract': 'not the abstract that you are looking for',
            'authors_display': 'bloggs, j'
        })
        _, code, _ = metadata.metadata('POST', params, self.session,
                                       submission_id)
        self.assertEqual(code, status.OK, "Returns 200 OK")
        self.assertEqual(mock_save.call_count, 0, "No events are generated")

    @mock.patch(f'{metadata.__name__}.CoreMetadataForm.Meta.csrf', False)
    @mock.patch(f'{metadata.__name__}.save')
    @mock.patch('arxiv.submission.load')
    def test_post_request_some_changed_data(self, mock_load, mock_save):
        """POST request with valid data; only the title has changed."""
        submission_id = 2
        mock_submission = mock.MagicMock(
            submission_id=submission_id,
            is_finalized=False,
            metadata=mock.MagicMock(
                title='the old title',
                abstract='not the abstract that you are looking for',
                authors_display='bloggs, j'
            )
        )
        mock_load.return_value = (mock_submission, [])
        mock_save.return_value = (mock_submission, [])
        params = MultiDict({
            'title': 'the new title',
            'abstract': 'not the abstract that you are looking for',
            'authors_display': 'bloggs, j'
        })
        _, code, _ = metadata.metadata('POST', params, self.session,
                                       submission_id)
        self.assertEqual(code, status.OK, "Returns 200 OK")
        self.assertEqual(mock_save.call_count, 1, "One event is generated")
        self.assertIsInstance(mock_save.call_args[0][0], SetTitle,
                              "SetTitle is generated")

    @mock.patch(f'{metadata.__name__}.CoreMetadataForm.Meta.csrf', False)
    @mock.patch(f'{metadata.__name__}.save')
    @mock.patch('arxiv.submission.load')
    def test_post_request_invalid_data(self, mock_load, mock_save):
        """POST request with invalid data."""
        submission_id = 2
        mock_submission = mock.MagicMock(
            submission_id=submission_id,
            is_finalized=False,
            metadata=mock.MagicMock(
                title='the old title',
                abstract='not the abstract that you are looking for',
                authors_display='bloggs, j'
            )
        )
        mock_load.return_value = (mock_submission, [])
        mock_save.return_value = (mock_submission, [])
        params = MultiDict({
            'title': 'the new title',
            'abstract': 'too short',
            'authors_display': 'bloggs, j'
        })
        data, _, _ = metadata.metadata('POST', params, self.session, submission_id)
        self.assertIsInstance(data['form'], Form, "Data includes a form")

    @mock.patch(f'{metadata.__name__}.CoreMetadataForm.Meta.csrf', False)
    @mock.patch(f'{metadata.__name__}.save')
    @mock.patch('arxiv.submission.load')
    def test_save_error_is_raised(self, mock_load, mock_save):
        """POST request results in an SaveError exception."""
        submission_id = 2
        mock_submission = mock.MagicMock(
            submission_id=submission_id,
            is_finalized=False,
            metadata=mock.MagicMock(
                title='the old title',
                abstract='not the abstract that you are looking for',
                authors_display='bloggs, j'
            )
        )
        mock_load.return_value = (mock_submission, [])

        def raise_save_error(*args, **kwargs):
            raise events.SaveError('nope')

        mock_save.side_effect = raise_save_error
        params = MultiDict({
            'title': 'a new, valid title',
            'abstract': 'this abstract is at least twenty characters long',
            'authors_display': 'j doe, j bloggs'
        })
        with self.assertRaises(InternalServerError):
            metadata.metadata('POST', params, self.session, submission_id)
