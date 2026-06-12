"""Phase 2 oversize tests at the UI/persistence level.

These use the composable submission fixtures from ``submit_ce/ui/conftest.py``.
"""

from flask import current_app

from submit_ce.domain.event.file import UploadFiles


def test_oversize_upload_sets_flag(sub_files_oversize):
    """An oversize upload flags the submission but does not hold it yet."""
    assert sub_files_oversize.is_oversize is True
    # The auto-hold is only applied at finalize; a working submission is not
    # on hold yet.
    assert sub_files_oversize.is_on_hold is False


def test_normal_upload_not_oversize(sub_files):
    assert sub_files.is_oversize is False


def test_oversize_flag_persists_on_event(app, sub_files_oversize):
    """The event's oversize reasons round-trip through the event history."""
    with app.app_context():
        _, history = current_app.api.get_with_history(
            str(sub_files_oversize.submission_id))
        uploads = [e for e in history if isinstance(e, UploadFiles)]
        assert uploads and uploads[-1].oversize
        assert uploads[-1].oversize[0].kind == "TOTAL"
