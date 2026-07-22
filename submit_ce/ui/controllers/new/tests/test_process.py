"""Tests for :mod:`submit_ce.controllers.process`."""

import io
from http import HTTPStatus as status

from werkzeug.datastructures import MultiDict
from flask import current_app, request

from submit_ce.domain.agent import InternalClient
from submit_ce.domain.event import SetSourceFormat
from submit_ce.domain.event.process import StartCompileSource
from submit_ce.domain.uploads import SourceFormat
from submit_ce.implementations.compile.mock_compile_mimesis_pdf import MockCompileMimesisPdf
from submit_ce.implementations.file_store.mock_file_store import MockFileStore
from submit_ce.ui.controllers.new.process import compile_status, file_process


class _CountingCompiler(MockCompileMimesisPdf):
    """Counts start_compile calls and writes a preview only when asked.

    With ``produce_preview=False`` it models a compile that ran but produced no
    usable PDF (e.g. TeX errors) -- a ``StartCompileSource`` event is still
    recorded, but no preview lands, so we can assert the Process page does not
    silently recompile the same broken source on every arrival. [SUBMISSION-75]
    """

    def __init__(self, produce_preview: bool = True) -> None:
        super().__init__()
        self.compile_calls = 0
        self._produce_preview = produce_preview

    def start_compile(self, submission, user, client, api, source_package_id=None):
        self.compile_calls += 1
        if self._produce_preview:
            return super().start_compile(submission, user, client, api,
                                         source_package_id)
        # Ran, but produced no preview.
        from datetime import datetime, timezone
        from submit_ce.domain.event.process import Result
        from submit_ce.domain.process import ProcessStatus
        return Result(
            status=ProcessStatus(status=ProcessStatus.Status.SUCCEEDED,
                                 creator=user, created=datetime.now(timezone.utc),
                                 details={}),
            duration_sec=0, utc_start_time=datetime.now(timezone.utc),
            url="FAKE")


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


def test_file_process_tex_autocompiles_on_arrival(
        app, authorized_user_session, sub_files_tex):
    """TeX source with no prior compile: arriving at Process (GET) initiates
    compilation automatically -- no button click needed. [SUBMISSION-75]"""
    session, _ = authorized_user_session
    with app.test_request_context("/"):
        # compile_status instantiates a CSRF form, which needs an active
        # session on the request. We call the controller directly (rather than
        # via the test client) so we can inject the mock store/compiler and
        # assert on them, so set request.auth ourselves. [SUBMISSION-75]
        request.auth = session
        sid = str(sub_files_tex.submission_id)
        store = MockFileStore()
        current_app.api.store = store
        current_app.api.compiler = MockCompileMimesisPdf()

        assert not store.does_preview_exist(sid)

        rdata, code, _ = file_process("GET", MultiDict(), session, sid, token="")

        assert code == status.OK
        # A preview was produced and the page reflects success ...
        assert store.does_preview_exist(sid)
        assert rdata.get('status') == 'succeeded'
        # ... and a compile event is now recorded for the current source.
        _, events = current_app.api.get_with_history(sid)
        assert any(isinstance(e, StartCompileSource) for e in events)


def test_file_process_tex_reuses_existing_preview(
        app, authorized_user_session, sub_files_tex):
    """A valid preview already exists and the source is unchanged: arriving at
    Process must NOT recompile -- the existing result is reused. [SUBMISSION-75]"""
    session, _ = authorized_user_session
    with app.test_request_context("/"):
        # compile_status instantiates a CSRF form, which needs an active
        # session on the request. We call the controller directly (rather than
        # via the test client) so we can inject the mock store/compiler and
        # assert on them, so set request.auth ourselves. [SUBMISSION-75]
        request.auth = session
        sid = str(sub_files_tex.submission_id)
        store = MockFileStore()
        current_app.api.store = store
        counting = _CountingCompiler()
        current_app.api.compiler = counting
        # Seed a current preview as if a previous compile had succeeded.
        store.store_preview(sid, io.BytesIO(b"%PDF-EXISTING\n%%EOF\n"))

        _, code, _ = file_process("GET", MultiDict(), session, sid, token="")

        assert code == status.OK
        assert counting.compile_calls == 0  # reused, not recompiled


def test_file_process_tex_does_not_retry_failed_compile_on_refresh(
        app, authorized_user_session, sub_files_tex):
    """A compile that produced no preview (e.g. TeX errors) is attempted once;
    revisiting/refreshing Process must not silently recompile the same broken
    source. The submitter retries explicitly via Reprocess. [SUBMISSION-75]"""
    session, _ = authorized_user_session
    sid = str(sub_files_tex.submission_id)
    # Store/compiler live on the app-level api so they persist across the two
    # separate request contexts below. Each context is a distinct arrival with
    # a fresh `g`, so the second GET reloads the submission from the DB and sees
    # the StartCompileSource event the first one recorded (mirroring two real
    # HTTP requests, rather than reusing a cached snapshot). [SUBMISSION-75]
    store = MockFileStore()
    app.api.store = store
    counting = _CountingCompiler(produce_preview=False)
    app.api.compiler = counting

    # First arrival: auto-compile runs, but yields no preview.
    with app.test_request_context("/"):
        request.auth = session  # compile_status builds a CSRF form -> needs session
        file_process("GET", MultiDict(), session, sid, token="")
    assert counting.compile_calls == 1
    assert not store.does_preview_exist(sid)

    # Second arrival (fresh request/g cache): must not re-trigger.
    with app.test_request_context("/"):
        request.auth = session
        file_process("GET", MultiDict(), session, sid, token="")
    assert counting.compile_calls == 1


def test_compile_status_shows_current_log(
        app, authorized_user_session, sub_files_tex, mocker):
    """A compile log that exists is current -- any file change deletes it (see
    ``_common_file_change_execute``) -- so ``compile_status`` surfaces it on the
    Process page, whether the compile succeeded or failed. This also guards
    against the request-cached-event pitfall: the log shows on first arrival,
    not only after a refresh. [SUBMISSION-75]"""
    session, _ = authorized_user_session
    with app.test_request_context("/"):
        # compile_status instantiates a CSRF form, which needs an active
        # session on the request. We call the controller directly (rather than
        # via the test client) so we can inject the mock store and assert on the
        # rendered data, so set request.auth ourselves. [SUBMISSION-75]
        request.auth = session
        sid = str(sub_files_tex.submission_id)

        fake = mocker.MagicMock()
        fake.get_preview.return_value.exists.return_value = True
        log = mocker.MagicMock()
        log.exists.return_value = True
        log.download_as_text.return_value = "COMPILER LOG OUTPUT"
        fake.get_compile_log.return_value = log
        mocker.patch.object(app.api, 'get_file_store', return_value=fake)

        rdata, code, _ = compile_status(MultiDict(), session, sid, token="")

        assert code == status.OK
        assert rdata.get('compile_log') == "COMPILER LOG OUTPUT"


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


def test_file_process_pdf_only_skips_install_when_not_one_pdf(
        app, authorized_user, authorized_user_session, sub_primary):
    """If a PDF-only submission has other than exactly one PDF, the install is
    rejected under the lock (InvalidEvent) and handled gracefully: no 500, no
    preview installed, submission not marked source-processed. [SUBMISSION-196]"""
    session, _ = authorized_user_session
    ua = InternalClient(name="test_pdf_only")
    with app.app_context():
        sid = str(sub_primary.submission_id)

        store = MockFileStore()
        current_app.api.store = store
        current_app.api.compiler = MockCompileMimesisPdf()
        # PDF-only by format, but two PDFs in the workspace (invariant violated).
        store._source[sid] = {"a.pdf": b"%PDF-1.4\n%%EOF\n",
                              "b.pdf": b"%PDF-1.4\n%%EOF\n"}
        current_app.api.save(
            SetSourceFormat(creator=authorized_user, client=ua,
                            source_format=SourceFormat.PDF.value),
            submission_id=sid)

        _, code, _ = file_process("GET", MultiDict(), session, sid, token="")

        assert code == status.OK
        assert not store.does_preview_exist(sid)
        submission, _ = current_app.api.get_with_history(sid)
        assert submission.is_source_processed is False


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
