"""
Additional edge-path coverage for the event domain.

Focus
-----
Hit validation/error branches that were still untested in
submit_ce/domain/event/__init__.py:

- ConfirmPreview: no preview / checksum mismatch / correct checksum
- CreateSubmissionVersion: .validate requires an announced submission
- Rollback: version==1 (delete), version>1 with history, invalid scenarios
- SetReportNumber: invalid vs. valid formats
"""

from datetime import datetime
from pytz import UTC
import copy
import pytest
from unittest import mock

from qa.checks import TitleIsValid
from qa.checks.models import Disposition, Result

# Domain models and helpers
from submit_ce.domain import submission as submod, agent
from submit_ce.domain.preview import Preview
from submit_ce.domain.submission import Submission
from submit_ce.domain.uploads import SourceFormat

# Event classes (and exception)
from submit_ce.domain.event import (
    ConfirmPreview,
    CreateSubmissionVersion,
    FinalizeSubmission,
    RemoveSecondaryClassification,
    Rollback,
    SetAbstract,
    SetLicense,
    SetReportNumber,
    SetTitle,
    InvalidEvent,
)


# -----------------------------
# Local helpers (tiny fixtures)
# -----------------------------

# UTC 'now' for created/submitted timestamps.
def _now():
    return datetime.now(UTC)

# Minimal PublicUser
def _user(uid: str = "u1"):
    return agent.PublicUser(
        name="Test User",
        user_id=uid,
        email=f"{uid}@example.org",
        endorsements=[],
    )

# Minimal "working" submission (unannounced)
def _working_submission(uid: str = "u1"):
    u = _user(uid)
    return submod.Submission(creator=u, owner=u, created=_now())

# Minimal "announced" submission (has arxiv_id + ANNOUNCED status)
def _announced_submission(uid: str = "u1", arxiv_id: str = "2501.01234"):
    s = _working_submission(uid)
    s.arxiv_id = arxiv_id
    s.status = submod.Submission.ANNOUNCED
    # event.Announce expects .versions to exist, but for these tests we only
    # need to represent an already-announced state, not run Announce.
    s.versions = [copy.deepcopy(s)]
    return s

# -------------------------------------------------------
# ConfirmPreview: three cases (no preview / mismatch / ok)
# -------------------------------------------------------

def test_confirm_preview_fails_when_no_preview_for_tex():
    """
    ConfirmPreview should fail for TeX submissions if submission.preview
    is None -- TeX requires a separately-compiled preview produced by the
    Process step's ConfirmSourceProcessed event.
    """
    s = _working_submission()
    s.source_format = SourceFormat.TEX
    e = ConfirmPreview(creator=s.creator, created=_now(), preview_checksum="abc123")
    with pytest.raises(InvalidEvent):
        e.validate_pre_lock(s)

def test_confirm_preview_fails_on_checksum_mismatch_for_tex():
    """
    For TeX submissions, ConfirmPreview should fail if provided
    preview_checksum != submission.preview.preview_checksum.
    """
    s = _working_submission()
    s.source_format = SourceFormat.TEX
    s.preview = Preview(
        source_id=1,
        source_checksum="SRC",
        preview_checksum="EXPECTED",
        size_bytes=100,
        added=_now(),
    )
    e = ConfirmPreview(creator=s.creator, created=_now(), preview_checksum="WRONG")
    with pytest.raises(InvalidEvent):
        e.validate_pre_lock(s)

def test_confirm_preview_succeeds_on_checksum_match_sets_flag_for_tex():
    """
    For TeX submissions, ConfirmPreview should pass when checksums match
    and set submitter_confirmed_preview.
    """
    s = _working_submission()
    s.source_format = SourceFormat.TEX
    s.preview = Preview(
        source_id=1,
        source_checksum="SRC",
        preview_checksum="MATCH",
        size_bytes=100,
        added=_now(),
    )
    e = ConfirmPreview(creator=s.creator, created=_now(), preview_checksum="MATCH")
    # validate should not raise
    e.validate_pre_lock(s)
    # apply should toggle the flag
    after = e.apply(s)
    assert after.submitter_confirmed_preview is True


# -------------------------------------------------------
# ConfirmPreview: PDF / HTML / POSTSCRIPT cases
# These cover the validator's source-format branching. The validator
# only requires submission.preview for source formats that go through
# the compile pipeline (TEX, POSTSCRIPT). For PDF / HTML / other
# non-processing formats the source IS the preview, so confirmation
# can succeed without submission.preview ever being set. This mirrors
# the workflow's has_non_processing_content condition in
# submit_ce/ui/workflow/conditions.py.
# -------------------------------------------------------

def test_confirm_preview_pdf_no_preview_passes():
    """
    For PDF-only submissions, ConfirmPreview should pass even when
    submission.preview is None -- the source PDF IS the preview, no
    separate compilation step runs.
    """
    s = _working_submission()
    s.source_format = SourceFormat.PDF
    e = ConfirmPreview(
        creator=s.creator, created=_now(),
        preview_checksum="anything-since-not-checked",
    )
    # Should not raise
    e.validate_pre_lock(s)
    after = e.apply(s)
    assert after.submitter_confirmed_preview is True

def test_confirm_preview_html_no_preview_passes():
    """
    For HTML submissions, ConfirmPreview should pass without
    submission.preview -- same rationale as PDF: no compile step.
    """
    s = _working_submission()
    s.source_format = SourceFormat.HTML
    e = ConfirmPreview(
        creator=s.creator, created=_now(),
        preview_checksum="anything",
    )
    e.validate_pre_lock(s)
    after = e.apply(s)
    assert after.submitter_confirmed_preview is True

def test_confirm_preview_postscript_requires_preview():
    """
    PostScript submissions go through the compile pipeline the same way
    TeX does, so ConfirmPreview should still require submission.preview
    for PostScript -- mirrors has_non_processing_content() which excludes
    both TEX and POSTSCRIPT from the "non-processing" set.
    """
    s = _working_submission()
    s.source_format = SourceFormat.POSTSCRIPT
    e = ConfirmPreview(creator=s.creator, created=_now(), preview_checksum="abc")
    with pytest.raises(InvalidEvent):
        e.validate_pre_lock(s)


# -------------------------------------------------------
# CreateSubmissionVersion: requires announced submission
# -------------------------------------------------------

def test_create_submission_version_rejects_unannounced():
    """
    CreateSubmissionVersion.validate requires submission.is_announced.
    """
    s = _working_submission()
    e = CreateSubmissionVersion(creator=s.creator, created=_now())
    with pytest.raises(InvalidEvent):
        e.validate_pre_lock(s)

def test_create_submission_version_succeeds_when_announced():
    """
    CreateSubmissionVersion should pass validate for announced submissions
    and yield a new working version on apply().
    """
    s = _announced_submission()
    e = CreateSubmissionVersion(creator=s.creator, created=_now())
    # validate should not raise
    e.validate_pre_lock(s)
    # apply should move to a new version and set status to WORKING
    after = e.apply(s)
    assert after.version == s.version + 1
    assert after.status == submod.Submission.WORKING
    # and un-set fields like preview confirmation
    assert after.submitter_confirmed_preview is False

# -------------------------------------------------------
# FinalizeSubmission
# -------------------------------------------------------
def test_finalize_missing_required_fields():
    s = _working_submission()
    e = FinalizeSubmission(creator=s.creator)
    with pytest.raises(InvalidEvent):
        e.validate_pre_lock(s)  # REQUIRED / REQUIRED_METADATA guard

# -------------------------------------------------------
# RemoveSecondaryClassification
# -------------------------------------------------------
def test_remove_secondary_missing_fails():
    s = _working_submission()
    # category not yet added → _must_already_be_present should fail
    e = RemoveSecondaryClassification(creator=s.creator, category="cs.AI")
    with pytest.raises(InvalidEvent):
        e.validate_pre_lock(s)  # "No such category on submission"

# -------------------------------------------------------
# Rollback: version==1 -> delete; version>1 with history -> revert
# -------------------------------------------------------

def test_rollback_invalid_when_announced():
    s = _announced_submission()
    e = Rollback(creator=s.creator)
    with pytest.raises(InvalidEvent):
        e.validate_pre_lock(s)  # "Cannot already be announced"

def test_rollback_on_first_version_deletes_submission():
    """
    Rollback.project with version==1 should set status=DELETED.
    """
    s = _working_submission()
    s.version = 1
    e = Rollback(creator=s.creator, created=_now())
    # validate: requires unannounced (is true for working)
    e.validate_pre_lock(s)
    after = e.apply(s)
    assert after.status == submod.Submission.DELETED

def test_rollback_to_previous_announced_version():
    """
    Rollback.project on version>1 should step back to last snapshot in .versions.
    """
    s = _announced_submission()
    # simulate we're now on version 2 with prior announced snapshot saved
    s.status = submod.Submission.WORKING
    s.version = 2
    # Add a previous announced snapshot as in Announce
    s.versions = [copy.deepcopy(s)]
    s.versions[0].status = submod.Submission.ANNOUNCED
    e = Rollback(creator=s.creator, created=_now())
    e.validate_pre_lock(s)
    after = e.apply(s)
    # Should have decremented version and restored announced status
    assert after.version == 1
    assert after.status == submod.Submission.ANNOUNCED

def test_rollback_version1_sets_deleted():
    s = _working_submission()
    s.version = 1
    s.status = Submission.WORKING
    e = Rollback(creator=s.creator)
    e.validate_pre_lock(s)
    out = e.project(s)
    assert out.status == Submission.DELETED

# -------------------------------------------------------
# SetAbstract
# -------------------------------------------------------
def test_abstract_valid_passes():
    s = _working_submission()
    e = SetAbstract(creator=s.creator, abstract="This abstract is just long enough")
    e.validate_pre_lock(s)
    s2 = e.project(s)
    assert s2.metadata.abstract == "This abstract is just long enough"

# -------------------------------------------------------
# SetLicense
# -------------------------------------------------------
def test_license_requires_url():
    s = _working_submission()
    e = SetLicense(creator=s.creator, license_name="CC BY 4.0", license_uri="")
    with pytest.raises(InvalidEvent):
        e.validate_pre_lock(
            s)  # "License must have a URL"

def test_license_valid_url():
    # Use a URI present in LICENSES and current; pick one from your config
    s = _working_submission()
    e = SetLicense(creator=s.creator, license_name="CC BY 4.0",
                   license_uri="http://creativecommons.org/licenses/by/4.0/")
    e.validate_pre_lock(s)  # passes if LICENSES marks it current

# -------------------------------------------------------
# SetReportNumber: invalid vs. valid formats
# -------------------------------------------------------

def test_set_report_number_accepts_common_formats():
    """
    SetReportNumber.validate accepts values with consecutive digits (e.g. '1003.1130').
    """
    s = _working_submission()
    e = SetReportNumber(creator=s.creator, report_num="CORNELL-1003-1130")
    # Should not raise
    e.validate_pre_lock(s)
    after = e.apply(s)
    assert after.metadata.report_num == "CORNELL-1003-1130"

# -------------------------------------------------------
# SetTitle
# -------------------------------------------------------
def test_title_allows_basic_tags():
    """<br> is in ALLOWED_HTML, so SetTitle._check_for_html should not block it.

    TitleIsValid.check is mocked to an OK Result so this test exercises only
    submit-ce's own bleach-based HTML check, independent of qa's checks.
    """
    s = _working_submission()
    e = SetTitle(creator=s.creator, title="Hello<br>World")
    ok_result = Result(check_config={}, passed=True, disposition=Disposition.OK, message="")
    with mock.patch.object(TitleIsValid, "check", return_value=ok_result):
        e.validate_pre_lock(s)

def test_title_rejects_disallowed_html():
    s = _working_submission()
    e = SetTitle(creator=s.creator, title="<script>alert(1)</script>")
    with pytest.raises(InvalidEvent):
        e.validate_pre_lock(s)  # _check_for_html branch

def test_title_trailing_period_rule():
    s = _working_submission()
    e = SetTitle(creator=s.creator, title="Hello world.")
    with pytest.raises(InvalidEvent):
        e.validate_pre_lock(s)  # validators.no_trailing_period
