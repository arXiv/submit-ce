"""Tests for upload_delete controllers (delete_file, delete_all, delete_dir)."""
from http import HTTPStatus as status
from types import SimpleNamespace

from submit_ce.ui.tests.csrf_util import parse_csrf_token


def _ws(mocker, *paths):
    """A workspace mock whose .files carry the given source-relative paths.

    Files include `bytes` because RemoveFiles.execute evaluates workspace
    oversize (reads file.bytes) when it runs.
    """
    ws = mocker.MagicMock()
    ws.size = 0
    ws.files = [SimpleNamespace(path=p, name=p.rsplit('/', 1)[-1], bytes=0)
                for p in paths]
    return ws


def test_delete_file_get(app, authorized_client, sub_files):
    """GET shows the deletion confirmation form with the file path pre-filled."""
    sub = sub_files
    resp = authorized_client.get(
        f"/{sub.submission_id}/file_delete",
        query_string={'path': 'paper.pdf'},
    )
    assert resp.status_code == status.OK
    assert b"Delete Files" in resp.data
    assert b"paper.pdf" in resp.data


def test_delete_file_post_without_confirm(app, authorized_client, sub_files):
    """POST without confirmation re-shows the form."""
    sub = sub_files
    url = f"/{sub.submission_id}/file_delete"
    resp = authorized_client.get(url, query_string={'path': 'paper.pdf'})
    csrf = parse_csrf_token(resp)

    resp = authorized_client.post(url, data={
        'csrf_token': csrf,
        'file_path': 'paper.pdf',
    })
    assert resp.status_code == status.OK
    assert b"Delete Files" in resp.data


def test_delete_file_post_confirmed(app, authorized_client, sub_files, mocker):
    """POST with confirmation calls delete on the file store and redirects to file_upload."""
    sub = sub_files
    url = f"/{sub.submission_id}/file_delete"
    resp = authorized_client.get(url, query_string={'path': 'paper.pdf'})
    csrf = parse_csrf_token(resp)

    mock_store = mocker.patch.object(app.api, 'store')
    mock_store.delete_source_file.return_value.bytes = 1
    # RemoveFiles re-evaluates the size limits, which reads the workspace.
    ws = mocker.MagicMock()
    ws.size = 0
    ws.files = []
    mock_store.get_workspace.return_value = ws

    resp = authorized_client.post(url, data={
        'csrf_token': csrf,
        'file_path': 'paper.pdf',
        'confirmed': 'true',
    })
    assert resp.status_code == status.SEE_OTHER
    assert resp.headers['Location'] == f"/{sub.submission_id}/file_upload"
    mock_store.delete_source_file.assert_called_once_with(
        str(sub.submission_id), 'paper.pdf'
    )


def test_delete_dir_get(app, authorized_client, sub_files, mocker):
    """GET shows the confirmation form listing only the files under the
    directory prefix (SUBMISSION-229)."""
    sub = sub_files
    mock_store = mocker.patch.object(app.api, 'store')
    mock_store.get_workspace.return_value = _ws(
        mocker, 'fig/a.png', 'fig/b.png', 'main.tex')

    resp = authorized_client.get(f"/{sub.submission_id}/file_delete_dir",
                                 query_string={'prefix': 'fig/'})
    assert resp.status_code == status.OK
    assert b"Delete Directory" in resp.data
    assert b"fig/a.png" in resp.data and b"fig/b.png" in resp.data
    assert b"main.tex" not in resp.data          # outside the directory


def test_delete_dir_post_without_confirm(app, authorized_client, sub_files, mocker):
    """POST without confirmation re-shows the form and deletes nothing."""
    sub = sub_files
    url = f"/{sub.submission_id}/file_delete_dir"
    mock_store = mocker.patch.object(app.api, 'store')
    mock_store.get_workspace.return_value = _ws(mocker, 'fig/a.png')

    resp = authorized_client.get(url, query_string={'prefix': 'fig/'})
    csrf = parse_csrf_token(resp)
    resp = authorized_client.post(url, data={'csrf_token': csrf,
                                             'dir_prefix': 'fig/'})
    assert resp.status_code == status.OK
    mock_store.delete_source_file.assert_not_called()


def test_delete_dir_post_confirmed(app, authorized_client, sub_files, mocker):
    """POST with confirmation deletes exactly the files under the prefix (not
    siblings) and redirects to file_upload (SUBMISSION-229)."""
    sub = sub_files
    url = f"/{sub.submission_id}/file_delete_dir"
    mock_store = mocker.patch.object(app.api, 'store')
    mock_store.delete_source_file.return_value.bytes = 1
    mock_store.get_workspace.return_value = _ws(
        mocker, 'fig/a.png', 'fig/b.png', 'main.tex')

    resp = authorized_client.get(url, query_string={'prefix': 'fig/'})
    csrf = parse_csrf_token(resp)
    resp = authorized_client.post(url, data={
        'csrf_token': csrf,
        'dir_prefix': 'fig/',
        'confirmed': 'true',
    })
    assert resp.status_code == status.SEE_OTHER
    assert resp.headers['Location'] == f"/{sub.submission_id}/file_upload"

    deleted = {c.args[1] for c in mock_store.delete_source_file.call_args_list}
    assert deleted == {'fig/a.png', 'fig/b.png'}     # only files under fig/
    assert 'main.tex' not in deleted


def test_delete_all_get(app, authorized_client, sub_files):
    """GET shows the delete-all confirmation form."""
    sub = sub_files
    resp = authorized_client.get(f"/{sub.submission_id}/file_delete_all")
    assert resp.status_code == status.OK
    assert b"Delete All Files" in resp.data


def test_delete_all_post_without_confirm(app, authorized_client, sub_files):
    """POST without confirmation re-shows the form."""
    sub = sub_files
    url = f"/{sub.submission_id}/file_delete_all"
    resp = authorized_client.get(url)
    csrf = parse_csrf_token(resp)

    resp = authorized_client.post(url, data={'csrf_token': csrf})
    assert resp.status_code == status.OK
    assert b"Delete All Files" in resp.data


def test_delete_all_post_confirmed(app, authorized_client, sub_files, mocker):
    """POST with confirmation calls delete on the file store and redirects to file_upload."""
    sub = sub_files
    url = f"/{sub.submission_id}/file_delete_all"
    resp = authorized_client.get(url)
    csrf = parse_csrf_token(resp)

    mock_store = mocker.MagicMock()
    mock_store.delete_source_file.return_value.bytes = 1
    mocker.patch.object(app.api, 'get_file_store', return_value=mock_store)
    mocker.patch.object(app.api, 'store', mock_store)

    resp = authorized_client.post(url, data={
        'csrf_token': csrf,
        'confirmed': 'true',
    })
    assert resp.status_code == status.SEE_OTHER
    assert resp.headers['Location'] == f"/{sub.submission_id}/file_upload"
    mock_store.delete_all_source_files.assert_called_once_with(str(sub.submission_id))
    mock_store.delete_preview.assert_called_once_with(str(sub.submission_id))
