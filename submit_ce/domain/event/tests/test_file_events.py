from datetime import datetime
from pytz import UTC

import pytest

from submit_ce.domain import submission as submod, agent
from submit_ce.domain.event.file import UploadFiles, RemoveFiles, RemoveAllFiles
from submit_ce.domain.uploads import SourceFormat
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
    e = UploadFiles(creator=s.creator, files=[])
    e.validate(s)
    s = e.project(s)

    assert s.submitter_confirmed_preview is False

def test_add_files_updates_package():
    s = _blank_submission()
    e = UploadFiles(creator=s.creator, files=[])

    e.validate(s)
    s = e.project(s)

    assert s.submitter_confirmed_preview is False

def test_remove_files_updates_size():
    s = _blank_submission()
    e = RemoveFiles(creator=s.creator, files=[])

    e.validate(s)
    s = e.project(s)

    assert s.submitter_confirmed_preview is False

def test_remove_all_files_clears_package():
    s = _blank_submission()
    e = RemoveAllFiles(creator=s.creator)

    e.validate(s)
    s = e.project(s)

    assert s.source_format is None
    assert s.uncompressed_size == 0
    assert s.submitter_confirmed_preview is False
