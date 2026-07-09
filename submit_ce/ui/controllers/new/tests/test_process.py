"""Tests for :mod:`submit_ce.controllers.process`."""

from http import HTTPStatus as status

from werkzeug.datastructures import MultiDict
from flask import current_app

from submit_ce.domain.agent import InternalClient
from submit_ce.domain.event import SetSourceFormat
from submit_ce.domain.uploads import SourceFormat
from submit_ce.implementations.file_store.mock_file_store import MockFileStore
from submit_ce.ui.controllers.new.process import file_process


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


def test_file_process_pdf_only_installs_preview(
        app, authorized_user, authorized_user_session, sub_primary):
    """PDF-only: transiting Process promotes the uploaded PDF into the
    top-level preview slot and records ConfirmSourceProcessed (Option A).

    Before the fix, the PDF branch of ``file_process`` just advanced without
    installing anything, leaving the preview slot empty -- ``/preview.pdf``
    404'd, ``ConfirmPreview`` never fired, and Submit stayed disabled.
    """
    session, _ = authorized_user_session
    ua = InternalClient(name="test_pdf_only")
    with app.app_context():
        sid = str(sub_primary.submission_id)

        store = MockFileStore()
        current_app.api.store = store
        # Seed a single uploaded PDF in the source workspace.
        store._source[sid] = {"paper.pdf": b"%PDF-1.4\n1 0 obj\n%%EOF\n"}

        # Mark the submission as PDF-only.
        current_app.api.save(
            SetSourceFormat(creator=authorized_user, client=ua,
                            source_format=SourceFormat.PDF.value),
            submission_id=sid)

        assert not store.does_preview_exist(sid)

        data, code, headers = file_process(
            "GET", MultiDict(), session, sid, token="")

        assert code == status.OK
        # The uploaded PDF is now installed at the top-level preview slot ...
        assert store.does_preview_exist(sid)
        assert store.get_preview(sid).download_as_bytes().startswith(b"%PDF")
        # ... and, on a fresh reload, the submission is marked source-processed.
        # NOTE: reload via get_with_history to bypass the per-request `g`
        # cache in backend.get_submission (which still holds the pre-event
        # snapshot inside this single app context). The legacy backend
        # round-trips is_source_processed via the must_process column;
        # submission.preview is derived state and is intentionally not
        # persisted, so we don't assert on it here (the Confirm-page gate
        # uses does_preview_exist + submitter_confirmed_preview instead).
        submission, _ = current_app.api.get_with_history(sid)
        assert submission.is_source_processed


def test_file_process_pdf_only_is_idempotent(
        app, authorized_user, authorized_user_session, sub_primary):
    """A second pass through Process must not re-install or error; once a
    preview exists the install is a no-op."""
    session, _ = authorized_user_session
    ua = InternalClient(name="test_pdf_only")
    with app.app_context():
        sid = str(sub_primary.submission_id)

        store = MockFileStore()
        current_app.api.store = store
        store._source[sid] = {"paper.pdf": b"%PDF-1.4\n%%EOF\n"}
        current_app.api.save(
            SetSourceFormat(creator=authorized_user, client=ua,
                            source_format=SourceFormat.PDF.value),
            submission_id=sid)

        file_process("GET", MultiDict(), session, sid, token="")
        first = store.get_preview(sid).download_as_bytes()

        # Change the source so an unexpected re-copy would be visible.
        store._source[sid] = {"paper.pdf": b"%PDF-DIFFERENT\n%%EOF\n"}
        data, code, headers = file_process(
            "GET", MultiDict(), session, sid, token="")

        assert code == status.OK
        # Idempotent: preview unchanged because it already existed.
        assert store.get_preview(sid).download_as_bytes() == first
