"""End-to-end: finalizing an oversize submission auto-applies a hold.

Exercises the Event.consequences() mechanism through the real save loop:
FinalizeSubmission declares AddHold as a consequence and emits it when the
submission is oversize, and the save loop persists it in the same transaction.
"""

import io
from types import SimpleNamespace
from unittest.mock import MagicMock

from flask import current_app

from submit_ce.domain.agent import InternalClient
from submit_ce.domain.event import FinalizeSubmission
from submit_ce.domain.event.file import UploadFiles
from submit_ce.domain.event.flag import AddHold
from submit_ce.domain.submission import Hold, Submission


def _make_oversize(user, submission_id):
    """Re-upload with a workspace over the size limit to flip is_oversize."""
    ua = InternalClient(name="test_client_finalize_oversize")
    big = 60 * 1024 * 1024  # over the 50 MB default limit

    class _FakePdf:
        filename = "huge.pdf"
        content_type = "application/pdf"
        stream = io.BytesIO(b"%PDF-1.4\n%%EOF\n")

    fake_stat = MagicMock()
    fake_stat.bytes = big
    mock_store = MagicMock()
    mock_store.store_source_file.return_value = fake_stat
    big_ws = MagicMock()
    big_ws.size = big
    big_ws.files = [SimpleNamespace(path="huge.pdf", bytes=big)]
    mock_store.get_workspace.return_value = big_ws

    original_store = current_app.api.store
    current_app.api.store = mock_store
    try:
        submission, _ = current_app.api.save(
            UploadFiles(creator=user, client=ua, files=[_FakePdf()]),
            submission_id=submission_id)
    finally:
        current_app.api.store = original_store
    return submission


def test_finalize_oversize_applies_hold(app, authorized_user, sub_metadata):
    """An oversize, metadata-complete submission gets a SOURCE_OVERSIZE hold
    on finalize, and the AddHold lands in the event history."""
    with app.app_context():
        user = authorized_user
        ua = InternalClient(name="test_client_finalize_oversize")
        sid = sub_metadata.submission_id

        oversize = _make_oversize(user, sid)
        assert oversize.is_oversize is True

        submission, events = current_app.api.save(
            FinalizeSubmission(creator=user, client=ua), submission_id=sid)

        assert submission.status == Submission.SUBMITTED
        holds = [h for h in submission.holds.values()
                 if h.hold_type == Hold.Type.SOURCE_OVERSIZE]
        assert len(holds) == 1
        assert submission.is_on_hold is True

        # The consequence is persisted as a real event in the history.
        _, history = current_app.api.get_with_history(str(sid))
        assert any(isinstance(e, AddHold) for e in history)


def test_finalize_normal_no_hold(app, authorized_user, sub_metadata):
    """A normal-size submission finalizes without a hold."""
    with app.app_context():
        user = authorized_user
        ua = InternalClient(name="test_client_finalize_oversize")
        submission, _ = current_app.api.save(
            FinalizeSubmission(creator=user, client=ua),
            submission_id=sub_metadata.submission_id)
        assert submission.is_oversize is False
        assert submission.holds == {}
        assert submission.is_on_hold is False
