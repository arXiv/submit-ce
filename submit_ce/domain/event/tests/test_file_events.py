from datetime import datetime
from pytz import UTC

from submit_ce.domain import submission as submod, agent
from submit_ce.domain.preview import Preview
from submit_ce.domain.event.file import (
    UploadFiles, RemoveFiles, RemoveAllFiles, _common_file_change_execute,
)

def _now():
    return datetime.now(UTC)

def _user(uid: str = "u1"):
    return agent.PublicUser(
        name="Test User",
        user_id=uid,
        email=f"{uid}@example.org",
        endorsements=[],
    )

def _blank_submission(uid: str = "u1"):
    u = _user(uid)
    return submod.Submission(
        creator=u,
        owner=u,
        created=_now(),
    )

def test_add_files_initializes_package():
    s = _blank_submission()
    e = UploadFiles(creator=s.creator, files=[])
    e.validate_pre_lock(s)
    s = e.project(s)

    assert s.submitter_confirmed_preview is False

def test_add_files_updates_package():
    s = _blank_submission()
    e = UploadFiles(creator=s.creator, files=[])

    e.validate_pre_lock(s)
    s = e.project(s)

    assert s.submitter_confirmed_preview is False

def test_remove_files_updates_size():
    s = _blank_submission()
    e = RemoveFiles(creator=s.creator, files=[])

    e.validate_pre_lock(s)
    s = e.project(s)

    assert s.submitter_confirmed_preview is False

def test_remove_all_files_clears_package():
    s = _blank_submission()
    e = RemoveAllFiles(creator=s.creator)

    e.validate_pre_lock(s)
    s = e.project(s)

    assert s.source_format is None
    assert s.uncompressed_size == 0
    assert s.submitter_confirmed_preview is False


def _processed_submission():
    """A submission that has already been processed, with a preview recorded."""
    s = _blank_submission()
    s.is_source_processed = True
    s.submitter_confirmed_preview = True
    s.preview = Preview(source_id=1, source_checksum="a",
                        preview_checksum="b", size_bytes=10, added=_now())
    return s


def test_upload_resets_processing_state():
    """Uploading files after a submission is processed marks it unprocessed and
    drops the stale preview, so Process re-runs on the new source. [SUBMISSION-207]"""
    s = _processed_submission()
    e = UploadFiles(creator=s.creator, files=[])
    e.validate_pre_lock(s)
    s = e.project(s)

    assert s.is_source_processed is False
    assert s.preview is None
    assert s.submitter_confirmed_preview is False


def test_remove_all_resets_processing_state():
    """RemoveAllFiles (e.g. swapping a processed PDF-only submission's file) also
    resets the processing state and clears the preview. [SUBMISSION-207]"""
    s = _processed_submission()
    e = RemoveAllFiles(creator=s.creator)
    e.validate_pre_lock(s)
    s = e.project(s)

    assert s.is_source_processed is False
    assert s.preview is None
    assert s.submitter_confirmed_preview is False


def test_file_change_deletes_compile_log(mocker):
    """Any source file change invalidates the compile log alongside the other
    derived artifacts, so a stale log can't linger on the Process page after the
    source it described has changed. [SUBMISSION-75]"""
    api = mocker.MagicMock()
    store = api.get_file_store.return_value
    submission = mocker.MagicMock()
    submission.submission_id = "123"

    _common_file_change_execute(api, submission)

    store.delete_compile_log.assert_called_once_with("123")
