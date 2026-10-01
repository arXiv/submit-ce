"""Tests for :func:`conditions.has_passed_pdf_preflight`.

Review Files completes for a PDF-only submission once ``PassPdfPreflight`` was
saved after the last file change -- the PDF counterpart of
``has_current_directives`` for TeX.
"""

from datetime import datetime

import pytest
from pytz import UTC

from submit_ce.domain import agent, submission as submod
from submit_ce.domain.event.file import UploadFiles
from submit_ce.domain.event.process import PassPdfPreflight, StartDirectives
from submit_ce.domain.exceptions import InvalidEvent
from submit_ce.domain.uploads import SourceFormat
from submit_ce.ui.workflow import conditions


def _user() -> agent.PublicUser:
    return agent.PublicUser(name="Test User", user_id="u1",
                            email="u1@example.org", endorsements=[])


def _submission(source_format) -> submod.Submission:
    u = _user()
    return submod.Submission(creator=u, owner=u, created=datetime.now(UTC),
                             source_format=source_format)


def _upload() -> UploadFiles:
    return UploadFiles(creator=_user(), files=[])


def _pass() -> PassPdfPreflight:
    return PassPdfPreflight(creator=_user())


def test_pdf_without_pass_is_not_passed():
    assert conditions.has_passed_pdf_preflight(
        _submission(SourceFormat.PDF), [_upload()]) is False


def test_pdf_pass_after_upload_is_passed():
    assert conditions.has_passed_pdf_preflight(
        _submission(SourceFormat.PDF), [_upload(), _pass()]) is True


def test_file_change_after_pass_invalidates_it():
    assert conditions.has_passed_pdf_preflight(
        _submission(SourceFormat.PDF), [_upload(), _pass(), _upload()]) is False


def test_pass_never_counts_for_tex():
    assert conditions.has_passed_pdf_preflight(
        _submission(SourceFormat.TEX), [_upload(), _pass()]) is False


def test_pdf_no_longer_short_circuits_current_directives():
    # PDF used to count as "directives current" unconditionally, which let a
    # PDF-only submission skip Review Files without preflight.
    assert conditions.has_current_directives(
        _submission(SourceFormat.PDF), [_upload()]) is False
    assert conditions.has_current_directives(
        _submission(SourceFormat.TEX),
        [_upload(), StartDirectives(creator=_user())]) is True


def test_pass_event_rejects_non_pdf():
    with pytest.raises(InvalidEvent):
        _pass().validate_pre_lock(_submission(SourceFormat.TEX))
    _pass().validate_pre_lock(_submission(SourceFormat.PDF))
