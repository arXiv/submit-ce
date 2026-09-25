"""Tests for :mod:`submit_ce.controllers.upload`."""


import posixpath
from datetime import datetime
from http import HTTPStatus as status
from unittest import mock

import pytest

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
            self.assertEqual(mock_api.save.call_count, 2,
                             'Saves UploadFiles and SetSourceFormat via the api')
        self.assertEqual(code, status.OK)
        self.assertEqual(get_controllers_desire(data), STAGE_RESHOW,
                         'Successful upload and reshow form')

    @mock.patch(f'{upload.__name__}.AddfilesForm.Meta.csrf', False)
    def test_oversize_warning_reads_50_MiB(self):
        """An oversize upload flashes a warning naming the 50 MiB limit.

        The displayed limit must read as the IEC binary "50.00 MiB" (the
        50 * 1024 * 1024 byte guideline), not a decimal-MB conversion such as
        "52.4 MB"/"51.2 MB" or an off-by-rounding "49.9 MB".
        """
        submission_id = 2
        mock_submission = mock.MagicMock(
            submission_id=submission_id, uncompressed_size=593920,
            is_finalized=False, is_announced=False, arxiv_id=None, version=1,
            is_oversize=True,
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
        mock_file = mock.MagicMock(filename='thebestfile.pdf',
                                   content_type='application/pdf')
        files = MultiDict({'file': mock_file})
        with self.app.app_context():
            mock_api = mock.MagicMock()
            mock_api.get_with_history.return_value = (mock_submission, [])
            mock_api.save.return_value = (mock_submission, [])
            mock_api.get_file_store.return_value.get_workspace.return_value = \
                workspace
            with mock.patch.object(self.app, 'api', mock_api), \
                    mock.patch(f'{upload.__name__}.alerts') as mock_alerts:
                upload.upload_files('POST', params, self.session,
                                    submission_id, files=files,
                                    token='footoken')

            warnings = [str(call.args[0])
                        for call in mock_alerts.flash_warning.call_args_list]
        oversize = [w for w in warnings if 'size guideline' in w]
        self.assertEqual(len(oversize), 1,
                         'Exactly one oversize warning is flashed')
        message = oversize[0]
        self.assertIn('50.00 MiB', message,
                      'Limit reads as the IEC binary 50.00 MiB')



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
            self.assertEqual(mock_api.save.call_count, 2,
                             'Saves RemoveFiles and SetSourceFormat via the api')
        self.assertEqual(code, status.OK)
        self.assertEqual(get_controllers_desire(data), STAGE_PARENT,
                         'Confirmed delete returns to the parent stage')


def _files(*paths):
    return [FileStatus(path=path, name=posixpath.basename(path),
                       content_type='application/octet-stream', bytes=1,
                       crc32c='fakecrc', url=f'https://example.com/{path}',
                       is_versioned=True, modified=datetime.now(),
                       ancillary=path.startswith('anc/'))
            for path in paths]


def test_infer_source_format_html_with_images_and_css():
    """HTML plus the images and stylesheet it links to is HTML. [SUBMISSION-127]"""
    files = _files('index.html', 'image1.png', 'styles.css')
    assert upload._infer_source_format(files) == SourceFormat.HTML


def test_infer_source_format_html_any_case_in_subdirectory():
    assert upload._infer_source_format(_files('talks/INDEX.HTML')) == SourceFormat.HTML


def test_infer_source_format_htm_is_not_html():
    """Like Submission 1.5, whose preflight looks only for .html files."""
    assert upload._infer_source_format(_files('index.htm')) == SourceFormat.TEX


def test_infer_source_format_ignores_ancillary_html():
    files = _files('figure.png', 'anc/index.html')
    assert upload._infer_source_format(files) == SourceFormat.TEX


@pytest.mark.parametrize('source', ['main.tex', 'paper.ltx', 'macros.sty'])
def test_infer_source_format_tex_source_wins_over_html(source):
    """Any file preflight parses as TeX rules out HTML, as in Submission 1.5."""
    files = _files(source, 'index.html')
    assert upload._infer_source_format(files) == SourceFormat.TEX


def test_infer_source_format_html_with_30_files_is_invalid():
    """Legacy rejects HTML with 30 or more files, not counting ancillary files."""
    files = _files('index.html', *[f'fig{i}.png' for i in range(28)], 'anc/data.csv')
    assert upload._infer_source_format(files) == SourceFormat.HTML
    files += _files('fig28.png')
    assert upload._infer_source_format(files) == SourceFormat.INVALID


def test_notifications_detected_html():
    submission = mock.MagicMock(source_format=SourceFormat.HTML)
    workspace = mock.MagicMock(status=UploadStatus.READY, files=_files('index.html'))
    titles = [n['title'] for n in upload._get_notifications(submission, workspace)]
    assert 'Detected HTML' in titles


def test_notifications_too_many_html_files():
    submission = mock.MagicMock(source_format=SourceFormat.INVALID)
    files = _files('index.html', *[f'fig{i}.png' for i in range(29)])
    workspace = mock.MagicMock(status=UploadStatus.READY, files=files)
    bodies = [n['body'] for n in upload._get_notifications(submission, workspace)]
    assert any('too many image files' in body for body in bodies)
