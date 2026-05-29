"""Tests for :mod:`submit_ce.controllers.process`."""

from http import HTTPStatus as status


def test_no_sub(app, authorized_client):
    resp = authorized_client.get("/93489292/file_process")
    assert resp.status_code == status.NOT_FOUND
    resp = authorized_client.get("/93489292/file_upload")
    assert resp.status_code == status.NOT_FOUND
    resp = authorized_client.get("/93489292/confirm_delete")
    assert resp.status_code == status.NOT_FOUND
    resp = authorized_client.get("/93489292/confirm_delete_all")
    assert resp.status_code == status.NOT_FOUND
    resp = authorized_client.get("/93489292/preview.pdf")
    assert resp.status_code == status.NOT_FOUND

def test_process(app, authorized_client, sub_reviewfiles):
    sub = sub_reviewfiles
    url = f"/{sub.submission_id}/file_process"
    resp = authorized_client.get(url)
    assert resp.status_code == status.OK and \
        b"<title>Process Files" in resp.data \
        and b"<form " in resp.data
