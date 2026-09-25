"""Tests for :func:`submit_ce.ui.controllers.new.preview.file_preview`."""

import arxiv.db.models as classic
from arxiv.db import Session
from flask import current_app, request
from werkzeug.datastructures import MultiDict

from submit_ce.domain.agent import InternalClient
from submit_ce.domain.event import SetSourceFormat
from submit_ce.domain.uploads import SourceFormat
from submit_ce.implementations.compile.mock_compile_mimesis_pdf import MockCompileMimesisPdf
from submit_ce.implementations.file_store.mock_file_store import MockFileStore
from submit_ce.ui.controllers.new.preview import file_preview
from submit_ce.ui.controllers.new.process import file_process


def _view_pdf_preview(app, authorized_user, session, sid, owner_id=None):
    """Install a PDF-only submission's preview, optionally hand the submission
    to another owner, then open preview.pdf as the session's user."""
    with app.test_request_context("/"):
        request.auth = session
        store = MockFileStore()
        store.get_preview_checksum = lambda submission_id: "mock-preview-checksum"
        current_app.api.store = store
        current_app.api.compiler = MockCompileMimesisPdf()
        store._source[sid] = {"paper.pdf": b"%PDF-1.4\n%%EOF\n"}
        current_app.api.save(
            SetSourceFormat(creator=authorized_user, client=InternalClient(name="test"),
                            source_format=SourceFormat.PDF.value),
            submission_id=sid)
        file_process("GET", MultiDict(), session, sid, token="")
        if owner_id is not None:
            with Session() as db:
                db.get(classic.Submission, int(sid)).submitter_id = owner_id
                db.commit()
    with app.test_request_context("/"):
        request.auth = session
        file_preview(MultiDict(), session, sid, token="")
        submission, _ = current_app.api.get_with_history(sid)
    return submission


def test_file_preview_by_the_owner_confirms_it(
        app, authorized_user, authorized_user_session, sub_primary):
    session, _ = authorized_user_session
    submission = _view_pdf_preview(app, authorized_user, session,
                                   str(sub_primary.submission_id))
    assert submission.submitter_confirmed_preview


def test_file_preview_by_someone_else_does_not_confirm_it(
        app, authorized_user, authorized_user_session, sub_primary):
    """An admin opening the PDF is not the submitter reviewing it, so it must
    not unlock Submit."""
    session, _ = authorized_user_session
    submission = _view_pdf_preview(app, authorized_user, session,
                                   str(sub_primary.submission_id), owner_id=900001)
    assert not submission.submitter_confirmed_preview
