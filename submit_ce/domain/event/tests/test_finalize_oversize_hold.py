"""Unit tests for FinalizeSubmission.consequences() oversize -> hold logic.

These exercise the pure domain method directly, with hand-built submissions,
so no app or file store is needed.
"""

from datetime import datetime

from pytz import UTC

from submit_ce.domain import agent
from submit_ce.domain.meta import Classification
from submit_ce.domain.event import FinalizeSubmission, AddHold, \
    EmailSubmitterFinalizeMsg, EmailModeratorsFinalizeMsg
from submit_ce.domain.submission import Submission, Hold, Waiver, SubmissionType


def _user():
    return agent.PublicUser(name="Test User", user_id="u1",
                            email="u1@example.org", endorsements=[])


def _submission(is_oversize=False, waivers=None, submission_type=SubmissionType.NEW):
    u = _user()
    return Submission(
        creator=u, owner=u, created=datetime.now(UTC),
        primary_classification=Classification(category="astro-ph.GA"),
        is_oversize=is_oversize,
        submission_type=submission_type,
        waivers=waivers or {})


def _mod_emails(events):
    return [e for e in events if isinstance(e, EmailModeratorsFinalizeMsg)]


def _finalize():
    return FinalizeSubmission(creator=_user(), created=datetime.now(UTC))


def _holds(events):
    return [e for e in events if isinstance(e, AddHold)]


def test_oversize_finalize_yields_addhold():
    events = _finalize().consequences(_submission(is_oversize=True))
    holds = _holds(events)
    assert len(holds) == 1
    assert holds[0].hold_type == Hold.Type.SOURCE_OVERSIZE


def test_not_oversize_finalize_yields_no_hold():
    assert _holds(_finalize().consequences(_submission(is_oversize=False))) == []


def test_oversize_with_waiver_yields_no_hold():
    waiver = Waiver(event_id="w1", created=datetime.now(UTC), creator=_user(),
                    waiver_type=Hold.Type.SOURCE_OVERSIZE, waiver_reason="ok")
    sub = _submission(is_oversize=True, waivers={"w1": waiver})
    assert _holds(_finalize().consequences(sub)) == []


def test_finalize_always_emails_submitter():
    """Every finalize emits exactly one submitter confirmation email."""
    for is_oversize in (True, False):
        events = _finalize().consequences(_submission(is_oversize=is_oversize))
        emails = [e for e in events if isinstance(e, EmailSubmitterFinalizeMsg)]
        assert len(emails) == 1


def test_declared_consequence_type():
    assert FinalizeSubmission.CONSEQUENCE_TYPES == frozenset(
        {AddHold, EmailSubmitterFinalizeMsg, EmailModeratorsFinalizeMsg})


def test_new_finalize_emails_moderators():
    """A plain `new` submission notifies moderators on finalize."""
    events = _finalize().consequences(_submission())
    assert len(_mod_emails(events)) == 1


def test_auto_hold_finalize_does_not_email_moderators():
    """An auto-held (oversize) submission tells the submitter, not moderators."""
    events = _finalize().consequences(_submission(is_oversize=True))
    assert _mod_emails(events) == []


def test_jref_finalize_does_not_email_moderators():
    """`jref` has no moderator template in legacy; no moderator email."""
    sub = _submission(submission_type=SubmissionType.JOURNAL_REFERENCE)
    assert _mod_emails(_finalize().consequences(sub)) == []


def test_rep_wdr_cross_finalize_email_moderators():
    for sub_type in (SubmissionType.REPLACEMENT, SubmissionType.WITHDRAWAL,
                     SubmissionType.CROSS_LIST):
        events = _finalize().consequences(_submission(submission_type=sub_type))
        assert len(_mod_emails(events)) == 1, sub_type
