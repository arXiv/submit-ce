"""Tests for the ``StoreZzrm`` event. [SUBMISSION-205]

Exercise ``validate_pre_lock``/``execute``/``project`` directly with a
hand-rolled fake API (no Flask app or real file store), matching the style
of ``test_oversize_detection.py``.

The behavior under test: writing ``00README.json`` and invalidating the
now-stale source package must happen as one side effect, and the source
package must be *deleted* (lazy invalidation) rather than rebuilt here.
"""

from datetime import datetime

import pytest
from pytz import UTC

from submit_ce.domain import submission as submod, agent
from submit_ce.domain.event.process import StoreZzrm
from submit_ce.domain.exceptions import InvalidEvent


class _FakeStore:
    def __init__(self):
        self.calls = []
        self.zzrm = {}

    def store_zzrm(self, sid, content):
        self.calls.append(("store_zzrm", sid, content))
        self.zzrm[sid] = content

    def delete_source_package(self, sid):
        self.calls.append(("delete_source_package", sid))


class _FakeApi:
    def __init__(self):
        self._store = _FakeStore()

    def get_file_store(self):
        return self._store


def _user(uid="u1"):
    return agent.PublicUser(name="Test User", user_id=uid,
                            email=f"{uid}@example.org", endorsements=[])


def _submission(sid="1234567"):
    u = _user()
    s = submod.Submission(creator=u, owner=u, created=datetime.now(UTC))
    s.submission_id = sid
    return s


def test_execute_writes_zzrm_then_deletes_package():
    """execute writes 00README then drops the stale tar, in that order."""
    s = _submission()
    api = _FakeApi()
    e = StoreZzrm(creator=s.creator, zzrm={"process": {"compiler": "pdflatex"}})

    e.execute(api, s)

    assert api._store.zzrm[s.submission_id] == {"process": {"compiler": "pdflatex"}}
    # store_zzrm must precede delete_source_package (write, then invalidate).
    assert api._store.calls == [
        ("store_zzrm", s.submission_id, {"process": {"compiler": "pdflatex"}}),
        ("delete_source_package", s.submission_id),
    ]


def test_execute_does_not_rebuild_package():
    """We invalidate lazily -- no write_source_package/build here."""
    s = _submission()
    api = _FakeApi()
    e = StoreZzrm(creator=s.creator, zzrm={"a": 1})

    e.execute(api, s)

    called = {c[0] for c in api._store.calls}
    assert "write_source_package" not in called
    assert "build_source_package" not in called


def test_project_is_noop():
    """The side effect is the file write; the submission state is unchanged."""
    s = _submission()
    e = StoreZzrm(creator=s.creator, zzrm={"a": 1})
    assert e.project(s) is s


def test_validate_pre_lock_requires_submission_id():
    s = _submission(sid=None)
    e = StoreZzrm(creator=s.creator, zzrm={"a": 1})
    with pytest.raises(InvalidEvent):
        e.validate_pre_lock(s)
