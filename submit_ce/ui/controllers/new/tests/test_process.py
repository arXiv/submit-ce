"""Tests for :mod:`submit_ce.controllers.process`."""

from http import HTTPStatus as status

from werkzeug.datastructures import MultiDict
from flask import current_app

from submit_ce.domain.agent import InternalClient
from submit_ce.domain.event import SetSourceFormat
from submit_ce.domain.uploads import SourceFormat
from submit_ce.implementations.compile.mock_compile_mimesis_pdf import MockCompileMimesisPdf
from submit_ce.implementations.file_store.mock_file_store import MockFileStore
from submit_ce.ui.controllers.new.process import file_process


class _StampFails(MockCompileMimesisPdf):
    """A compiler whose stamp() always fails, to exercise the fallback."""

    def stamp(self, pdf_bytes, watermark_text, watermark_link=None):
        raise RuntimeError("stamp service unavailable")


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


def test_file_process_pdf_only_installs_stamped_preview(
        app, authorized_user, authorized_user_session, sub_primary):
    """PDF-only: transiting Process stamps the uploaded PDF and installs the
    stamped preview (``<id>.pdf``) via InstallPdfPreview under the submission
    lock. No redundant unstamped copy is stored -- the original stays in
    ``src/``. [SUBMISSION-196]"""
    session, _ = authorized_user_session
    ua = InternalClient(name="test_pdf_only")
    src = b"%PDF-1.4\n1 0 obj\n%%EOF\n"
    with app.app_context():
        sid = str(sub_primary.submission_id)

        store = MockFileStore()
        current_app.api.store = store
        current_app.api.compiler = MockCompileMimesisPdf()  # stamp() -> b"STAMPED:" + bytes
        store._source[sid] = {"paper.pdf": src}
        current_app.api.save(
            SetSourceFormat(creator=authorized_user, client=ua,
                            source_format=SourceFormat.PDF.value),
            submission_id=sid)

        assert not store.does_preview_exist(sid)

        _, code, _ = file_process("GET", MultiDict(), session, sid, token="")

        assert code == status.OK
        # Stamped PDF is in the preview slot ...
        assert store.get_preview(sid).download_as_bytes() == b"STAMPED:" + src
        # ... and no redundant unstamped copy was written (original is in src/).
        assert sid not in store._nostamp_preview
        # ... and, on a fresh reload (bypassing the per-request g cache), the
        # submission is marked source-processed (round-trips via must_process).
        submission, _ = current_app.api.get_with_history(sid)
        assert submission.is_source_processed


def test_file_process_pdf_only_removes_stale_nostamp_from_prior_tex(
        app, authorized_user, authorized_user_session, sub_primary):
    """If a prior TeX compile left an ``<id>-nostamp.pdf`` and the submitter
    then switched to PDF-only, InstallPdfPreview removes the stale unstamped
    copy so it can't linger under the submission. [SUBMISSION-196]"""
    session, _ = authorized_user_session
    ua = InternalClient(name="test_pdf_only")
    src = b"%PDF-1.4\n1 0 obj\n%%EOF\n"
    with app.app_context():
        sid = str(sub_primary.submission_id)

        store = MockFileStore()
        current_app.api.store = store
        current_app.api.compiler = MockCompileMimesisPdf()
        store._source[sid] = {"paper.pdf": src}
        # Simulate a leftover unstamped PDF from a previous TeX compile.
        store._nostamp_preview[sid] = b"OLD-TEX-UNSTAMPED"
        current_app.api.save(
            SetSourceFormat(creator=authorized_user, client=ua,
                            source_format=SourceFormat.PDF.value),
            submission_id=sid)

        _, code, _ = file_process("GET", MultiDict(), session, sid, token="")

        assert code == status.OK
        # Stale unstamped copy removed; stamped preview installed.
        assert sid not in store._nostamp_preview
        assert store.get_preview(sid).download_as_bytes() == b"STAMPED:" + src


def test_file_process_pdf_only_falls_back_to_unstamped_on_stamp_failure(
        app, authorized_user, authorized_user_session, sub_primary):
    """If stamping fails, the preview slot must still be populated -- with the
    unstamped PDF -- so the submitter can review and Submit stays reachable."""
    session, _ = authorized_user_session
    ua = InternalClient(name="test_pdf_only")
    src = b"%PDF-1.4\n%%EOF\n"
    with app.app_context():
        sid = str(sub_primary.submission_id)

        store = MockFileStore()
        current_app.api.store = store
        current_app.api.compiler = _StampFails()
        store._source[sid] = {"paper.pdf": src}
        current_app.api.save(
            SetSourceFormat(creator=authorized_user, client=ua,
                            source_format=SourceFormat.PDF.value),
            submission_id=sid)

        _, code, _ = file_process("GET", MultiDict(), session, sid, token="")

        assert code == status.OK
        # Fallback: preview slot holds the unstamped bytes (no STAMPED marker).
        assert store.get_preview(sid).download_as_bytes() == src
        # No redundant unstamped copy is stored (original stays in src/).
        assert sid not in store._nostamp_preview


def test_file_process_pdf_only_does_not_confirm_preview(
        app, authorized_user, authorized_user_session, sub_primary):
    """Installing/stamping must NOT mark the preview as viewed. The submitter
    still has to open it to fire ConfirmPreview (the review gate) -- this
    guards against stamping accidentally bypassing the 'must review' rule."""
    session, _ = authorized_user_session
    ua = InternalClient(name="test_pdf_only")
    with app.app_context():
        sid = str(sub_primary.submission_id)

        store = MockFileStore()
        current_app.api.store = store
        current_app.api.compiler = MockCompileMimesisPdf()
        store._source[sid] = {"paper.pdf": b"%PDF-1.4\n%%EOF\n"}
        current_app.api.save(
            SetSourceFormat(creator=authorized_user, client=ua,
                            source_format=SourceFormat.PDF.value),
            submission_id=sid)

        file_process("GET", MultiDict(), session, sid, token="")

        submission, _ = current_app.api.get_with_history(sid)
        assert submission.is_source_processed
        # Viewable, but not yet viewed.
        assert submission.submitter_confirmed_preview is False


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
        current_app.api.compiler = MockCompileMimesisPdf()
        store._source[sid] = {"paper.pdf": b"%PDF-1.4\n%%EOF\n"}
        current_app.api.save(
            SetSourceFormat(creator=authorized_user, client=ua,
                            source_format=SourceFormat.PDF.value),
            submission_id=sid)

        file_process("GET", MultiDict(), session, sid, token="")
        first = store.get_preview(sid).download_as_bytes()

        # Change the source so an unexpected re-copy would be visible.
        store._source[sid] = {"paper.pdf": b"%PDF-DIFFERENT\n%%EOF\n"}
        _, code, _ = file_process("GET", MultiDict(), session, sid, token="")

        assert code == status.OK
        # Idempotent: preview unchanged because it already existed.
        assert store.get_preview(sid).download_as_bytes() == first
