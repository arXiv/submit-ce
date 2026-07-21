"""Tests for InstallPdfPreview.validate_under_lock. [SUBMISSION-196]

The event requires exactly one PDF in the source workspace. That precondition
lives in ``validate_under_lock`` (run under the submission row lock), so a
violated invariant rejects the event cleanly -- raising ``InvalidEvent`` --
instead of installing a partial or absent preview.

Unreachable in normal flow (``source_format == PDF`` implies a single lone PDF;
see ``_infer_source_format``); these tests guard the invariant.
"""

from datetime import datetime
from types import SimpleNamespace

import pytest
from pytz import UTC

from submit_ce.domain import submission as submod, agent
from submit_ce.domain.uploads import SourceFormat
from submit_ce.domain.exceptions import InvalidEvent
from submit_ce.domain.event.process import InstallPdfPreview


class _FakeStore:
    def __init__(self, files):
        self._files = files

    def get_workspace(self, submission_id):
        return SimpleNamespace(files=self._files)


class _FakeApi:
    def __init__(self, files):
        self._store = _FakeStore(files)

    def get_file_store(self):
        return self._store


def _user(uid="u1"):
    return agent.PublicUser(name="Test User", user_id=uid,
                            email=f"{uid}@example.org", endorsements=[])


def _pdf_submission(sid="1234567"):
    u = _user()
    s = submod.Submission(creator=u, owner=u, created=datetime.now(UTC),
                          source_format=SourceFormat.PDF)
    s.submission_id = sid
    return s


def _pdf_file(name):
    return SimpleNamespace(name=name, path=name, crc32c="c", bytes=10)


def _validate(files):
    s = _pdf_submission()
    api = _FakeApi(files)
    InstallPdfPreview(creator=s.creator).validate_under_lock(api, s)


def test_zero_pdfs_rejected():
    with pytest.raises(InvalidEvent):
        _validate([])


def test_multiple_pdfs_rejected():
    with pytest.raises(InvalidEvent):
        _validate([_pdf_file("a.pdf"), _pdf_file("b.pdf")])


def test_exactly_one_pdf_passes():
    # Should not raise.
    _validate([_pdf_file("paper.pdf")])
