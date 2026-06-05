"""Tests for :mod:`submit_ce.controllers.upload`."""


from datetime import datetime
from http import HTTPStatus as status
from unittest import mock

from werkzeug.datastructures import MultiDict


from submit_ce.domain.uploads import FileStatus, UploadLifecycleStates, UploadStatus, Workspace
from submit_ce.ui.controllers.new import upload


from submit_ce.domain.uploads import SourceFormat

from submit_ce.ui.controllers.new import upload_delete
from submit_ce.ui.tests import CtrlBase

from submit_ce.ui.routes.flow_control import (
    get_controllers_desire,
    STAGE_RESHOW,
    STAGE_PARENT,
)


def test_upload(app, authorized_client, sub_cross):
    sub = sub_cross
    url = f"/{sub.submission_id}/file_upload"
    resp = authorized_client.get(url)
    assert resp.status_code == status.OK and \
        b"<title>Upload" in resp.data \
        and b"<form " in resp.data

class TestUpload(CtrlBase):
    """Tests for :func:`submit_ce.controllers.upload`."""

    @mock.patch(f'{upload.__name__}.AddfilesForm.Meta.csrf', False)
    def test_get_no_upload(self):
        """GET request for submission with no upload package."""
        submission_id = 2
        subm = mock.MagicMock(submission_id=submission_id, uncompressed_size=0,
                              is_finalized=False, is_announced=False,
                              arxiv_id=None, version=1)
        params = MultiDict({})
        files = MultiDict({})
        with self.app.app_context():
            mock_api = mock.MagicMock()
            mock_api.get_with_history.return_value = (subm, [])
            with mock.patch.object(self.app, 'api', mock_api):
                data, code, _ = upload.upload_files('GET', params, self.session,
                                                    submission_id, files=files,
                                                    token='footoken')
        self.assertEqual(code, status.OK, 'Returns 200 OK')
        self.assertIn('submission_id', data, 'Submission is in response')
        self.assertIn('submission_id', data, 'ID is in response')

    @mock.patch(f'{upload.__name__}.AddfilesForm.Meta.csrf', False)
    @mock.patch(f'{upload.__name__}.alerts', mock.MagicMock())
    def test_get_upload(self):
        """GET request for submission with an existing upload package."""
        submission_id = 2
        subm = mock.MagicMock(submission_id=submission_id,
                              uncompressed_size=593920,
                              is_finalized=False, is_announced=False,
                              arxiv_id=None, version=1)
        workspace = Workspace(
            identifier='25',
            checksum='a1s2d3f4',
            size=593920,
            started=datetime.now(),
            completed=datetime.now(),
            created=datetime.now(),
            modified=datetime.now(),
            status=UploadStatus.READY,
            source_format=SourceFormat.TEX,
            lifecycle=UploadLifecycleStates.ACTIVE,
            locked=False,
            files=[FileStatus(
                path='',
                name='thebestfile.pdf',
                content_type='application/pdf',
                bytes=20505,
                crc32c='fakecrc',
                url='https://example.com/thebestfile.pdf',
                is_versioned=True,
                modified=datetime.now(),
                ancillary=False,
                errors=[]
            )],
            errors=[]
        )
        params = MultiDict({})
        files = MultiDict({})
        with self.app.app_context():
            mock_api = mock.MagicMock()
            mock_api.get_with_history.return_value = (subm, [])
            mock_api.get_file_store.return_value.get_workspace.return_value = \
                workspace
            with mock.patch.object(self.app, 'api', mock_api):
                data, code, _ = upload.upload_files('GET', params, self.session,
                                                    submission_id, files=files,
                                                    token='footoken')
            self.assertEqual(
                mock_api.get_file_store.return_value.get_workspace.call_count, 1,
                'Calls the file store service')
        self.assertEqual(code, status.OK, 'Returns 200 OK')
        self.assertIn('status', data, 'Upload status is in response')
        self.assertIn('submission', data, 'Submission is in response')
        self.assertIn('submission_id', data, 'ID is in response')
        
    @mock.patch(f'{upload.__name__}.AddfilesForm.Meta.csrf', False)
    @mock.patch(f'{upload.__name__}.alerts', mock.MagicMock())
    def test_post_upload(self):
        """POST request for submission with an existing upload package."""
        submission_id = 2
        mock_submission = mock.MagicMock(
            submission_id=submission_id, uncompressed_size=593920,
            is_finalized=False, is_announced=False, arxiv_id=None, version=1
        )
        workspace = Workspace(
            identifier='25',
            checksum='a1s2d3f4',
            size=593920,
            started=datetime.now(),
            completed=datetime.now(),
            created=datetime.now(),
            modified=datetime.now(),
            status=UploadStatus.READY,
            source_format=SourceFormat.TEX,
            lifecycle=UploadLifecycleStates.ACTIVE,
            locked=False,
            files=[FileStatus(
                path='',
                name='thebestfile.pdf',
                content_type='application/pdf',
                bytes=20505,
                crc32c='fakecrc',
                url='https://example.com/thebestfile.pdf',
                is_versioned=True,
                modified=datetime.now(),
                ancillary=False,
                errors=[]
            )],
            errors=[]
        )
        params = MultiDict({})
        # A non-archive file: real filename/content_type so it is not
        # misclassified as a tgz/zip archive by is_file_tgz/is_file_zip.
        mock_file = mock.MagicMock(filename='thebestfile.pdf',
                                   content_type='application/pdf')
        files = MultiDict({'file': mock_file})
        with self.app.app_context():
            mock_api = mock.MagicMock()
            mock_api.get_with_history.return_value = (mock_submission, [])
            mock_api.save.return_value = (mock_submission, [])
            mock_api.get_file_store.return_value.get_workspace.return_value = \
                workspace
            with mock.patch.object(self.app, 'api', mock_api):
                data, code, _ = upload.upload_files('POST', params, self.session,
                                                    submission_id, files=files,
                                                    token='footoken')
            self.assertEqual(mock_api.save.call_count, 1,
                             'Saves the upload command via the api')
        self.assertEqual(code, status.OK)
        self.assertEqual(get_controllers_desire(data), STAGE_RESHOW,
                         'Successful upload and reshow form')

class TestDelete(CtrlBase):
    """Tests for :func:`submit_ce.controllers.upload.delete`."""

    @mock.patch(f'{upload_delete.__name__}.DeleteFileForm.Meta.csrf', False)
    def test_get_delete(self):
        """GET request to delete a file."""
        submission_id = 2
        subm = mock.MagicMock(submission_id=submission_id,
                              is_finalized=False, is_announced=False,
                              arxiv_id=None, version=1)
        file_path = 'anc/foo.jpeg'
        params = MultiDict({'path': file_path})
        with self.app.app_context():
            mock_api = mock.MagicMock()
            mock_api.get_with_history.return_value = (subm, [])
            with mock.patch.object(self.app, 'api', mock_api):
                data, code, _ = upload_delete.delete_file('GET', params,
                                                          self.session,
                                                          submission_id,
                                                          'footoken')
        self.assertEqual(code, status.OK, "Returns 200 OK")
        self.assertIn('form', data, "Returns a form in response")
        self.assertEqual(data['form'].file_path.data, file_path, 'Path is set')

    @mock.patch(f'{upload_delete.__name__}.DeleteFileForm.Meta.csrf', False)
    def test_post_delete(self):
        """POST without confirmation stays on the stage and deletes nothing."""
        submission_id = 2
        subm = mock.MagicMock(submission_id=submission_id, is_finalized=False,
                              is_announced=False, arxiv_id=None, version=1)
        file_path = 'anc/foo.jpeg'
        params = MultiDict({'file_path': file_path})
        with self.app.app_context():
            mock_api = mock.MagicMock()
            mock_api.get_with_history.return_value = (subm, [])
            with mock.patch.object(self.app, 'api', mock_api):
                data, code, _ = upload_delete.delete_file('POST', params,
                                                          self.session,
                                                          submission_id, 'tok')
            self.assertEqual(mock_api.save.call_count, 0,
                             'Does not delete without confirmation')
        self.assertEqual(code, status.OK)
        self.assertEqual(get_controllers_desire(data), STAGE_RESHOW,
                         'Unconfirmed delete reshows the form')
        self.assertIn('form', data, "Returns a form in response")

    @mock.patch(f'{upload_delete.__name__}.DeleteFileForm.Meta.csrf', False)
    def test_post_delete_confirmed(self):
        """POST with confirmation deletes the file and returns to parent."""
        submission_id = 2
        subm = mock.MagicMock(submission_id=submission_id, is_finalized=False,
                              is_announced=False, arxiv_id=None, version=1)
        file_path = 'anc/foo.jpeg'
        params = MultiDict({'file_path': file_path, 'confirmed': True})
        with self.app.app_context():
            mock_api = mock.MagicMock()
            mock_api.get_with_history.return_value = (subm, [])
            mock_api.save.return_value = (subm, [])
            with mock.patch.object(self.app, 'api', mock_api):
                data, code, _ = upload_delete.delete_file('POST', params,
                                                          self.session,
                                                          submission_id,
                                                          'footoken')
            self.assertEqual(mock_api.save.call_count, 1,
                             'Saves the remove-files command via the api')
        self.assertEqual(code, status.OK)
        self.assertEqual(get_controllers_desire(data), STAGE_PARENT,
                         'Confirmed delete returns to the parent stage')
