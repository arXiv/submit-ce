"""Tests for :mod:`submit.controllers.upload`."""

from datetime import timedelta, datetime
from http import HTTPStatus as status
from pytz import timezone
from unittest import TestCase, mock

from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import BadRequest, InternalServerError
from wtforms import Form

from arxiv_auth import auth, domain
from arxiv.submission.domain.submission import SubmissionContent
from arxiv.submission.domain.uploads import Upload, FileStatus, FileError, \
    UploadLifecycleStates, UploadStatus
from arxiv.submission.services import filemanager

from submit.controllers.ui.new import upload
from submit.controllers.ui.new import upload_delete

from submit.routes.ui.flow_control import STAGE_SUCCESS, \
    get_controllers_desire, STAGE_RESHOW

class TestUpload(TestCase):
    """Tests for :func:`submit.controllers.upload`."""

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
                name=domain.UserFullName('Jane', 'Bloggs', 'III'),
                profile=domain.UserProfile(
                    affiliation='FSU',
                    rank=3,
                    country='de',
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

    @mock.patch(f'{upload.__name__}.UploadForm.Meta.csrf', False)
    @mock.patch('arxiv.submission.load')
    def test_get_no_upload(self, mock_load):
        """GET request for ui-app with no upload package."""
        submission_id = 2
        subm = mock.MagicMock(submission_id=submission_id, source_content=None,
                              is_finalized=False, is_announced=False,
                              arxiv_id=None, version=1)
        mock_load.return_value = (subm, [])
        params = MultiDict({})
        files = MultiDict({})
        data, code, _ = upload.upload_files('GET', params, files, self.session,
                                            submission_id, 'footoken')
        self.assertEqual(code, status.OK, 'Returns 200 OK')
        self.assertIn('ui-app', data, 'Submission is in response')
        self.assertIn('submission_id', data, 'ID is in response')

    @mock.patch(f'{upload.__name__}.UploadForm.Meta.csrf', False)
    @mock.patch(f'{upload.__name__}.alerts', mock.MagicMock())
    @mock.patch(f'{upload.__name__}.Filemanager')
    @mock.patch('arxiv.submission.load')
    def test_get_upload(self, mock_load, mock_Filemanager):
        """GET request for ui-app with an existing upload package."""
        submission_id = 2
        mock_load.return_value = (
            mock.MagicMock(
                submission_id=submission_id,
                source_content=SubmissionContent(
                    identifier='5433',
                    checksum='a1s2d3f4',
                    uncompressed_size=593920,
                    compressed_size=1000,
                    source_format=SubmissionContent.Format.TEX
                ),
                is_finalized=False, is_announced=False, arxiv_id=None,
                version=1
            ), []
        )
        mock_filemanager = mock.MagicMock()
        mock_filemanager.get_upload_status.return_value = (
            Upload(
                identifier=25,
                checksum='a1s2d3f4',
                size=593920,
                started=datetime.now(),
                completed=datetime.now(),
                created=datetime.now(),
                modified=datetime.now(),
                status=UploadStatus.READY,
                lifecycle=UploadLifecycleStates.ACTIVE,
                locked=False,
                files=[FileStatus(
                    path='',
                    name='thebestfile.pdf',
                    file_type='PDF',
                    modified=datetime.now(),
                    size=20505,
                    ancillary=False,
                    errors=[]
                )],
                errors=[]
            )
        )
        mock_Filemanager.current_session.return_value = mock_filemanager
        params = MultiDict({})
        files = MultiDict({})
        data, code, _ = upload.upload_files('GET', params, self.session,
                                            submission_id, files=files,
                                            token='footoken')
        self.assertEqual(code, status.OK, 'Returns 200 OK')
        self.assertEqual(mock_filemanager.get_upload_status.call_count, 1,
                         'Calls the file management service')
        self.assertIn('status', data, 'Upload status is in response')
        self.assertIn('ui-app', data, 'Submission is in response')
        self.assertIn('submission_id', data, 'ID is in response')

    @mock.patch(f'{upload.__name__}.UploadForm.Meta.csrf', False)
    @mock.patch(f'{upload.__name__}.alerts', mock.MagicMock())
    @mock.patch(f'{upload.__name__}.url_for', mock.MagicMock(return_value='/'))
    @mock.patch(f'{upload.__name__}.Filemanager')
    @mock.patch(f'{upload.__name__}.save')
    @mock.patch(f'arxiv.submission.load')
    def test_post_upload(self, mock_load, mock_save, mock_filemanager):
        """POST request for ui-app with an existing upload package."""
        submission_id = 2
        mock_submission = mock.MagicMock(
            submission_id=submission_id,
            source_content=SubmissionContent(
                identifier='5433',
                checksum='a1s2d3f4',
                uncompressed_size=593920,
                compressed_size=1000,
                source_format=SubmissionContent.Format.TEX
            ),
            is_finalized=False, is_announced=False, arxiv_id=None, version=1
        )
        mock_load.return_value = (mock_submission, [])
        mock_save.return_value = (mock_submission, [])
        mock_fm = mock.MagicMock()
        mock_fm.add_file.return_value = Upload(
            identifier=25,
            checksum='a1s2d3f4',
            size=593920,
            started=datetime.now(),
            completed=datetime.now(),
            created=datetime.now(),
            modified=datetime.now(),
            status=UploadStatus.READY,
            lifecycle=UploadLifecycleStates.ACTIVE,
            locked=False,
            files=[FileStatus(
                path='',
                name='thebestfile.pdf',
                file_type='PDF',
                modified=datetime.now(),
                size=20505,
                ancillary=False,
                errors=[]
            )],
            errors=[]
        )
        mock_filemanager.current_session.return_value = mock_fm
        params = MultiDict({})
        mock_file = mock.MagicMock()
        files = MultiDict({'file': mock_file})
        data, code, _ = upload.upload_files('POST', params, self.session,
                                            submission_id, files=files,
                                            token='footoken')
        
        self.assertEqual(code, status.OK)        
        self.assertEqual(get_controllers_desire(data), STAGE_RESHOW,
                         'Successful upload and reshow form')
        self.assertEqual(mock_fm.add_file.call_count, 1,
                         'Calls the file management service')
        self.assertTrue(mock_filemanager.add_file.called_with(mock_file))


class TestDelete(TestCase):
    """Tests for :func:`submit.controllers.upload.delete`."""

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
                name=domain.UserFullName('Jane', 'Bloggs', 'III'),
                profile=domain.UserProfile(
                    affiliation='FSU',
                    rank=3,
                    country='de',
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

    @mock.patch(f'{upload_delete.__name__}.DeleteFileForm.Meta.csrf', False)
    @mock.patch(f'{upload_delete.__name__}.Filemanager')
    @mock.patch('arxiv.submission.load')
    def test_get_delete(self, mock_load, mock_filemanager):
        """GET request to delete a file."""
        submission_id = 2
        mock_load.return_value = (
            mock.MagicMock(
                submission_id=submission_id,
                source_content=SubmissionContent(
                    identifier='5433',
                    checksum='a1s2d3f4',
                    uncompressed_size=593920,
                    compressed_size=1000,
                    source_format=SubmissionContent.Format.TEX
                ),
                is_finalized=False, is_announced=False, arxiv_id=None,
                version=1
            ), []
        )
        file_path = 'anc/foo.jpeg'
        params = MultiDict({'path': file_path})
        data, code, _ = upload_delete.delete_file('GET', params, self.session,
                                                  submission_id, 'footoken')
        self.assertEqual(code, status.OK, "Returns 200 OK")
        self.assertIn('form', data, "Returns a form in response")
        self.assertEqual(data['form'].file_path.data, file_path, 'Path is set')

    @mock.patch(f'{upload_delete.__name__}.alerts', mock.MagicMock())
    @mock.patch(f'{upload_delete.__name__}.DeleteFileForm.Meta.csrf', False)
    @mock.patch(f'{upload_delete.__name__}.Filemanager')
    @mock.patch('arxiv.submission.load')
    def test_post_delete(self, mock_load, mock_filemanager):
        """POST request to delete a file without confirmation."""
        submission_id = 2
        mock_load.return_value = (
            mock.MagicMock(
                submission_id=submission_id,
                source_content=SubmissionContent(
                    identifier='5433',
                    checksum='a1s2d3f4',
                    uncompressed_size=593920,
                    compressed_size=1000,
                    source_format=SubmissionContent.Format.TEX
                ),
                is_finalized=False, is_announced=False, arxiv_id=None,
                version=1
            ), []
        )
        file_path = 'anc/foo.jpeg'
        params = MultiDict({'file_path': file_path})
        try:
            upload_delete.delete_file('POST', params, self.session, submission_id, 'tok')
        except BadRequest as e:
            data = e.description
            self.assertIn('form', data, "Returns a form in response")

    @mock.patch(f'{upload_delete.__name__}.alerts', mock.MagicMock())
    @mock.patch(f'{upload_delete.__name__}.DeleteFileForm.Meta.csrf', False)
    @mock.patch(f'{upload_delete.__name__}.url_for')
    @mock.patch(f'{upload_delete.__name__}.Filemanager')
    @mock.patch(f'{upload_delete.__name__}.save')
    @mock.patch('arxiv.submission.load')
    def test_post_delete_confirmed(self, mock_load, mock_save,
                                   mock_filemanager, mock_url_for):
        """POST request to delete a file without confirmation."""
        redirect_uri = '/foo'
        mock_url_for.return_value = redirect_uri
        upload_id = '5433'
        submission_id = 2
        mock_load.return_value = (
            mock.MagicMock(
                submission_id=submission_id,
                source_content=SubmissionContent(
                    identifier=upload_id,
                    checksum='a1s2d3f4',
                    uncompressed_size=593920,
                    compressed_size=1000,
                    source_format=SubmissionContent.Format.TEX
                ),
                is_finalized=False, is_announced=False, arxiv_id=None,
                version=1
            ), []
        )
        mock_save.return_value = (
            mock.MagicMock(
                submission_id=submission_id,
                source_content=SubmissionContent(
                    identifier=upload_id,
                    checksum='a1s2d3f4',
                    uncompressed_size=593920,
                    compressed_size=1000,
                    source_format=SubmissionContent.Format.TEX
                ),
                is_finalized=False, is_announced=False, arxiv_id=None,
                version=1
            ), []
        )
        file_path = 'anc/foo.jpeg'
        params = MultiDict({'file_path': file_path, 'confirmed': True})
        data, code, _ = upload_delete.delete_file('POST', params, self.session, submission_id,
                                               'footoken')
        self.assertTrue(
            mock_filemanager.delete_file.called_with(upload_id, file_path),
            "Delete file method of file manager service is called"
        )
        self.assertEqual(code, status.OK)
        self.assertTrue(get_controllers_desire(data), STAGE_SUCCESS)
