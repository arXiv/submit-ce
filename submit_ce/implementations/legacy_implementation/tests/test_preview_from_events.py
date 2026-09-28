"""Restoring the processed PDF's record when a submission is loaded."""

from datetime import datetime, timedelta, timezone

from submit_ce.domain import agent
from submit_ce.domain.event import ConfirmSourceProcessed
from submit_ce.domain.event.file import UploadFiles
from submit_ce.domain.event.process import InstallPdfPreview, StartCompileSource
from submit_ce.domain.submission import Submission
from submit_ce.implementations.legacy_implementation.db import preview_from_events

USER = agent.PublicUser(name="Test User", user_id="u1", email="u1@example.org",
                        endorsements=[])
SECOND = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)


def _processed_row():
    """What ``to_submission`` loads from a row with ``must_process=0``."""
    return Submission(creator=USER, owner=USER, created=SECOND, is_source_processed=True)


def test_record_restored_when_the_compile_loads_after_its_confirm():
    """``created`` keeps whole seconds on MySQL, so a compile and the confirm
    that follows it in the same second can load in either order."""
    submission = _processed_row()
    preview_from_events(submission, [
        ConfirmSourceProcessed(creator=USER, created=SECOND, preview_checksum="built-pdf"),
        StartCompileSource(creator=USER, created=SECOND),
    ])
    assert submission.preview.preview_checksum == "built-pdf"


def test_no_tex_record_once_a_pdf_is_installed():
    submission = _processed_row()
    preview_from_events(submission, [
        ConfirmSourceProcessed(creator=USER, created=SECOND, preview_checksum="built-pdf"),
        UploadFiles(creator=USER, created=SECOND + timedelta(minutes=1), files=[]),
        InstallPdfPreview(creator=USER, created=SECOND + timedelta(minutes=2)),
    ])
    assert submission.preview is None
