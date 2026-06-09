"""Tests for oversize detection wired into the file-upload events.

These exercise ``execute``/``project`` directly with a hand-rolled fake API so
no Flask app or real file store is needed.
"""

from datetime import datetime
from types import SimpleNamespace

from pytz import UTC

from submit_ce.domain import submission as submod, agent
from submit_ce.domain.meta import Classification
from submit_ce.domain.event.file import (
    UploadFiles,
    UploadArchive,
    RemoveFiles,
    RemoveAllFiles,
)
from submit_ce.domain.size_limits import SizeLimits

MB = 1024 * 1024


class _FakeStore:
    def __init__(self, workspace):
        self.workspace = workspace

    def store_source_package(self, sid, content, chunk_size):
        return []

    def store_source_file(self, sid, content, chunk_size):
        return SimpleNamespace(bytes=0, path=getattr(content, "filename", "f"))

    def delete_source_file(self, sid, name):
        return None

    def delete_all_source_files(self, sid):
        pass

    def get_workspace(self, sid):
        return self.workspace

    def delete_preflight(self, sid):
        pass

    def delete_preview(self, sid):
        pass


class _FakeApi:
    def __init__(self, workspace, limits=None):
        self._store = _FakeStore(workspace)
        self._limits = limits or SizeLimits.defaults()

    def get_file_store(self):
        return self._store

    def get_size_limits(self):
        return self._limits


def _ws(total, per_file=None):
    per_file = per_file or {}
    files = [SimpleNamespace(path=p, bytes=b) for p, b in per_file.items()]
    return SimpleNamespace(size=total, files=files)


def _user(uid="u1"):
    return agent.PublicUser(name="Test User", user_id=uid,
                            email=f"{uid}@example.org", endorsements=[])


def _submission(category="astro-ph.GA"):
    u = _user()
    return submod.Submission(
        creator=u, owner=u, created=datetime.now(UTC),
        primary_classification=Classification(category=category))


def test_submission_defaults_not_oversize():
    assert _submission().is_oversize is False


def test_upload_files_flags_oversize():
    s = _submission()
    api = _FakeApi(_ws(60 * MB, {"huge.pdf": 60 * MB}))
    e = UploadFiles(creator=s.creator, files=[])
    e.execute(api, s)
    assert e.oversize is True
    s = e.project(s)
    assert s.is_oversize is True


def test_upload_files_within_limit_not_oversize():
    s = _submission()
    api = _FakeApi(_ws(10 * MB, {"ok.pdf": 10 * MB}))
    e = UploadFiles(creator=s.creator, files=[])
    e.execute(api, s)
    s = e.project(s)
    assert s.is_oversize is False


def test_upload_archive_flags_oversize():
    s = _submission()
    api = _FakeApi(_ws(80 * MB, {"a.tex": 80 * MB}))
    e = UploadArchive(creator=s.creator, file=None)
    e.execute(api, s)
    s = e.project(s)
    assert s.is_oversize is True


def test_remove_files_clears_oversize():
    s = _submission()
    s.is_oversize = True
    api = _FakeApi(_ws(5 * MB, {"small.tex": 5 * MB}))
    e = RemoveFiles(creator=s.creator, files=[])
    e.execute(api, s)
    s = e.project(s)
    assert s.is_oversize is False


def test_remove_all_files_clears_oversize():
    s = _submission()
    s.is_oversize = True
    e = RemoveAllFiles(creator=s.creator)
    s = e.project(s)
    assert s.is_oversize is False


def test_project_uses_persisted_flag_on_replay():
    # On replay execute() does not run; the flag comes from the stored event.
    s = _submission()
    e = UploadFiles(creator=s.creator, files=[], oversize=True)
    s = e.project(s)
    assert s.is_oversize is True


def test_no_workspace_is_not_oversize():
    s = _submission()
    api = _FakeApi(None)
    e = UploadFiles(creator=s.creator, files=[])
    e.execute(api, s)
    assert e.oversize is False


def test_per_archive_limit_used_in_event():
    s = _submission(category="astro-ph.GA")
    limits = SizeLimits(
        max_uncompressed_total={"default": 100 * MB, "astro-ph": 5 * MB},
        max_uncompressed_per_file={"default": 100 * MB},
        max_compressed={"default": 100 * MB},
    )
    api = _FakeApi(_ws(10 * MB, {"f": 10 * MB}), limits=limits)
    e = UploadFiles(creator=s.creator, files=[])
    e.execute(api, s)
    assert e.oversize is True  # 10 MB exceeds the 5 MB astro-ph total limit
