"""Tests for oversize detection wired into the file-upload events.

These exercise ``execute``/``project`` directly with a hand-rolled fake API so
no Flask app or real file store is needed.
"""

import io
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
from submit_ce.domain.size_limits import (
    SIZE_LIMIT_POLICY,
    SizeLimits,
    OversizeReason,
)

MB = 1024 * 1024


class _FakeStore:
    def __init__(self, workspace=None, unpacked=None):
        self.workspace = workspace
        self.unpacked = unpacked or []

    def store_source_package(self, sid, content, chunk_size):
        # The unpacked FileStatus list is configured per-test.
        return list(self.unpacked)

    def store_source_file(self, sid, content, chunk_size):
        # Echo the uploaded content's size so the file-delta size check sees a
        # real per-file/total contribution.
        return SimpleNamespace(bytes=content.bytes, path=content.filename)

    def delete_source_file(self, sid, name):
        return None

    def delete_all_source_files(self, sid):
        pass

    def get_workspace(self, sid):
        return self.workspace

    def delete_source_package(self, sid):
        pass

    def delete_preflight(self, sid):
        pass

    def delete_user_decisions(self, sid):
        pass

    def delete_directives(self, sid):
        pass

    def delete_preview(self, sid):
        pass


class _FakeApi:
    def __init__(self, workspace=None, limits=None, unpacked=None):
        self._store = _FakeStore(workspace, unpacked)
        self._limits = limits or SIZE_LIMIT_POLICY

    def get_file_store(self):
        return self._store

    def get_size_limits(self):
        return self._limits


def _ws(total, per_file=None):
    per_file = per_file or {}
    files = [SimpleNamespace(path=p, bytes=b) for p, b in per_file.items()]
    return SimpleNamespace(size=total, files=files)


def _upload(name, size):
    """An incoming upload object, as handed to ``UploadFiles.files``."""
    return SimpleNamespace(filename=name, bytes=size,
                           content_type="application/pdf",
                           stream=io.BytesIO(b"%PDF-1.4\n%%EOF\n"))


def _stat(path, size):
    """A stored-file status, as returned by the file store."""
    return SimpleNamespace(path=path, bytes=size)


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
    # Per-file limit below the total limit so one big file isolates PER_FILE.
    limits = SizeLimits(
        max_uncompressed_total={"default": 200 * MB},
        max_uncompressed_per_file={"default": 50 * MB},
        max_compressed={"default": 200 * MB},
    )
    s = _submission()
    api = _FakeApi(limits=limits)
    e = UploadFiles(creator=s.creator, files=[_upload("huge.pdf", 60 * MB)])
    e.execute(api, s)
    assert len(e.oversize) == 1
    assert e.oversize[0].kind == "PER_FILE"
    s = e.project(s)
    assert s.is_oversize is True


def test_upload_files_total_trips_via_accumulation():
    # The new file is under the per-file limit, but pushes the running total
    # (prior uncompressed_size + bytes_added) over the total limit. This is the
    # case that proves detection uses the file delta, not the workspace.
    s = _submission()
    s.uncompressed_size = 40 * MB
    api = _FakeApi()  # default 50 MB limits
    e = UploadFiles(creator=s.creator, files=[_upload("more.pdf", 20 * MB)])
    e.execute(api, s)
    assert len(e.oversize) == 1
    assert e.oversize[0].kind == "TOTAL"
    s = e.project(s)
    assert s.is_oversize is True
    assert s.uncompressed_size == 60 * MB


def test_upload_files_within_limit_not_oversize():
    s = _submission()
    api = _FakeApi()
    e = UploadFiles(creator=s.creator, files=[_upload("ok.pdf", 10 * MB)])
    e.execute(api, s)
    s = e.project(s)
    assert s.is_oversize is False


def test_upload_archive_flags_oversize():
    s = _submission()
    api = _FakeApi(unpacked=[_stat("a.tex", 80 * MB)])
    e = UploadArchive(creator=s.creator)
    e.file = _upload("a.tgz", 80 * MB)  # truthy; content ignored by the fake store
    e.execute(api, s)
    assert e.oversize
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
    # On replay execute() does not run; the reasons come from the stored event.
    s = _submission()
    reasons = [OversizeReason(kind="TOTAL", limit_bytes=50 * MB,
                              actual_bytes=60 * MB)]
    e = UploadFiles(creator=s.creator, files=[], oversize=reasons)
    s = e.project(s)
    assert s.is_oversize is True


def test_no_workspace_is_not_oversize():
    s = _submission()
    api = _FakeApi(None)
    e = UploadFiles(creator=s.creator, files=[])
    e.execute(api, s)
    assert not e.oversize


def test_per_archive_limit_used_in_event():
    s = _submission(category="astro-ph.GA")
    limits = SizeLimits(
        max_uncompressed_total={"default": 100 * MB, "astro-ph": 5 * MB},
        max_uncompressed_per_file={"default": 100 * MB},
        max_compressed={"default": 100 * MB},
    )
    api = _FakeApi(limits=limits)
    e = UploadFiles(creator=s.creator, files=[_upload("f", 10 * MB)])
    e.execute(api, s)
    assert e.oversize  # 10 MB exceeds the 5 MB astro-ph total limit
    assert e.oversize[0].kind == "TOTAL"
