"""Tests for InstallPdfPreview's skip-guard behavior. [SUBMISSION-196]

If ``execute()`` finds other than exactly one PDF in the source workspace it
returns early without installing anything; ``project()`` must then NOT mark
the submission source-processed or record a phantom preview.

This path is unreachable in normal flow -- ``source_format == PDF`` implies a
single lone PDF (see ``_infer_source_format``) -- so these tests guard against
a future change that lets the one-PDF invariant slip.
"""

from datetime import datetime
from types import SimpleNamespace

from pytz import UTC

from submit_ce.domain import submission as submod, agent
from submit_ce.domain.uploads import SourceFormat
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


def _execute_then_project(files):
    s = _pdf_submission()
    api = _FakeApi(files)
    e = InstallPdfPreview(creator=s.creator)
    e.execute(api, s)          # skips (returns early) when != 1 PDF
    return e.project(s)


def test_zero_pdfs_does_not_mark_processed():
    s = _execute_then_project([])
    assert s.is_source_processed is False
    assert s.preview is None


def test_multiple_pdfs_does_not_mark_processed():
    s = _execute_then_project([_pdf_file("a.pdf"), _pdf_file("b.pdf")])
    assert s.is_source_processed is False
    assert s.preview is None
