from datetime import datetime
from pytz import UTC

import pytest

from submit_ce.domain import submission as submod, agent
from submit_ce.domain.event.file import AddFiles, RemoveFiles, RemoveAllFiles
from submit_ce.domain.exceptions import InvalidEvent

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
    e = AddFiles(creator=s.creator, files=[], identifier="ws1", checksum="abc",
                 uncompressed_size=10, compressed_size=5,
                 source_format=submod.SubmissionContent.Format.PDF)
    e.validate(s)
    s = e.project(s)

    assert s.source_content is not None
    assert s.source_content.identifier == "ws1"
    assert s.source_content.checksum == "abc"
    assert s.source_content.uncompressed_size == 10
    assert s.source_content.source_format == submod.SubmissionContent.Format.PDF
    assert s.submitter_confirmed_preview is False

def test_add_files_updates_package():
    s = _blank_submission()
    s.source_content = submod.SubmissionContent(identifier="123", checksum="old", uncompressed_size=0, compressed_size=0)
    e = AddFiles(creator=s.creator, files=[], checksum="new_abc", uncompressed_size=10, compressed_size=5)

    e.validate(s)
    s = e.project(s)

    assert s.source_content.checksum == "new_abc"
    assert s.source_content.uncompressed_size == 10
    assert s.source_content.compressed_size == 5
    assert s.submitter_confirmed_preview is False

def test_remove_files_requires_upload_package():
    s = _blank_submission()
    e = RemoveFiles(creator=s.creator, files=[], checksum="abc", uncompressed_size=10, compressed_size=5)
    with pytest.raises(InvalidEvent, match="No upload package exists for this submission"):
        e.validate(s)

def test_remove_files_updates_package():
    s = _blank_submission()
    s.source_content = submod.SubmissionContent(identifier="123", checksum="old", uncompressed_size=20, compressed_size=10)
    e = RemoveFiles(creator=s.creator, files=[], checksum="new_abc", uncompressed_size=10, compressed_size=5)

    e.validate(s)
    s = e.project(s)

    assert s.source_content.checksum == "new_abc"
    assert s.source_content.uncompressed_size == 10
    assert s.source_content.compressed_size == 5
    assert s.submitter_confirmed_preview is False

def test_remove_all_files_requires_upload_package():
    s = _blank_submission()
    e = RemoveAllFiles(creator=s.creator, checksum="abc", uncompressed_size=0, compressed_size=0)
    with pytest.raises(InvalidEvent, match="No upload package exists for this submission"):
        e.validate(s)

def test_remove_all_files_updates_package():
    s = _blank_submission()
    s.source_content = submod.SubmissionContent(identifier="123", checksum="old", uncompressed_size=20, compressed_size=10)
    e = RemoveAllFiles(creator=s.creator, checksum="new_abc", uncompressed_size=0, compressed_size=0)

    e.validate(s)
    s = e.project(s)

    assert s.source_content.checksum == "new_abc"
    assert s.source_content.uncompressed_size == 0
    assert s.source_content.compressed_size == 0
    assert s.submitter_confirmed_preview is False
