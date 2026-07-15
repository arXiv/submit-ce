"""SUBMISSION-158: a submission with a general primary category may not carry
any secondary classifications. Enforced at finalize (every submission).

Edge cases (replacement-inherited and moderator/EUST-added secondaries) are
deferred to a follow-up and are not covered here.
"""

from datetime import datetime

from pytz import UTC
import pytest

from submit_ce.domain import agent, meta
from submit_ce.domain.uploads import SourceFormat
from submit_ce.domain.event import (
    AddSecondaryClassification,
    FinalizeSubmission,
    InvalidEvent,
    RemoveSecondaryClassification,
    SetPrimaryClassification,
)
from submit_ce.domain.submission import Submission, SubmissionMetadata

GENERAL_PRIMARY = "math.GM"      # is_general == True
SPECIFIC_PRIMARY = "astro-ph.GA"  # is_general == False
SECONDARY = "astro-ph.CO"


def _now():
    return datetime.now(UTC)


def _user():
    return agent.PublicUser(name="Test User", user_id="u1",
                            email="u1@example.org", endorsements=[])


def _finalizable(primary, secondaries, version=1):
    """An otherwise-finalizable submission with the given primary and
    secondary categories, so finalize can fail only on this rule."""
    u = _user()
    return Submission(
        creator=u, owner=u, created=_now(),
        version=version,
        source_format=SourceFormat("pdf"),
        license=meta.License(uri="http://free", name="free"),
        submitter_accepts_policy=True,
        primary_classification=meta.Classification(primary),
        secondary_classification=[meta.Classification(c) for c in secondaries],
        metadata=SubmissionMetadata(
            title="the best title",
            abstract="very abstract",
            authors_display="J K Jones, F W Englund",
        ),
    )


def _finalize():
    return FinalizeSubmission(creator=_user(), created=_now())


def test_general_primary_with_secondary_cannot_finalize():
    sub = _finalizable(GENERAL_PRIMARY, [SECONDARY])
    with pytest.raises(InvalidEvent, match="general primary category"):
        _finalize().validate_pre_lock(sub)


def test_general_primary_without_secondary_can_finalize():
    sub = _finalizable(GENERAL_PRIMARY, [])
    _finalize().validate_pre_lock(sub)  # does not raise


def test_specific_primary_with_secondary_can_finalize():
    """The rule only applies to general primaries."""
    sub = _finalizable(SPECIFIC_PRIMARY, [SECONDARY])
    _finalize().validate_pre_lock(sub)  # does not raise


def test_replacement_general_primary_with_inherited_secondary_can_finalize():
    """SUBMISSION-158 edge case 1: a replacement (version > 1) inherits its
    categories from the announced version and cannot change them, so a general
    primary with (grandfathered) secondaries must not block the replacement."""
    sub = _finalizable(GENERAL_PRIMARY, [SECONDARY], version=2)
    _finalize().validate_pre_lock(sub)  # does not raise


def test_new_submission_general_primary_with_secondary_still_blocked():
    """The exemption is only for replacements; a first-version submission with
    a general primary and a secondary is still blocked."""
    sub = _finalizable(GENERAL_PRIMARY, [SECONDARY], version=1)
    with pytest.raises(InvalidEvent, match="general primary category"):
        _finalize().validate_pre_lock(sub)


# ---------------------------------------------------------------------------
# The same check also runs on SetPrimaryClassification and
# AddSecondaryClassification, so the invalid combination is caught as the user
# builds it, not only at finalize. These tests exercise those two call sites
# and confirm the user cannot get stuck.
# ---------------------------------------------------------------------------

# Endorsed for everything so SetPrimaryClassification's endorsement check passes
# and we isolate the general-primary rule.
_USER = agent.PublicUser(name="Endorsed User", user_id="u2",
                         email="u2@example.org", endorsements=["*.*"])


def _sub(primary=None, secondaries=(), version=1):
    return Submission(
        creator=_USER, owner=_USER, created=_now(), version=version,
        primary_classification=meta.Classification(primary) if primary else None,
        secondary_classification=[meta.Classification(c) for c in secondaries])


def _set_primary(cat):
    return SetPrimaryClassification(creator=_USER, created=_now(), category=cat)


def _add_secondary(cat):
    return AddSecondaryClassification(creator=_USER, created=_now(), category=cat)


def _remove_secondary(cat):
    return RemoveSecondaryClassification(creator=_USER, created=_now(), category=cat)


# --- SetPrimaryClassification ---

def test_set_primary_general_with_no_secondaries_ok():
    """The common path: choosing a general primary on a submission with no
    secondaries is allowed, so the user is not blocked."""
    _set_primary(GENERAL_PRIMARY).validate_pre_lock(_sub())  # no raise


def test_set_primary_rejected_when_current_general_primary_has_secondary():
    """The check runs on SetPrimaryClassification: a submission that already
    carries a general primary with a secondary is rejected."""
    with pytest.raises(InvalidEvent, match="general primary category"):
        _set_primary(SPECIFIC_PRIMARY).validate_pre_lock(
            _sub(GENERAL_PRIMARY, [SECONDARY]))


def test_set_primary_toward_general_with_specific_current_ok():
    """Switching a *specific* primary (that has a secondary) toward a general
    one is not blocked by this event -- the check reads the current primary,
    which is still specific. The controller drops the secondary on save."""
    _set_primary(GENERAL_PRIMARY).validate_pre_lock(
        _sub(SPECIFIC_PRIMARY, [SECONDARY]))  # no raise


# --- AddSecondaryClassification ---

def test_add_first_secondary_to_general_primary_rejected():
    """The tightened check rejects even the first secondary added under a
    general primary (the add is blocked based on the primary alone)."""
    with pytest.raises(InvalidEvent, match="cross-list category may not be added"):
        _add_secondary(SECONDARY).validate_pre_lock(_sub(GENERAL_PRIMARY, []))


def test_add_secondary_rejected_when_general_primary_has_secondary():
    """Adding another secondary when a general primary already has one is
    also rejected."""
    with pytest.raises(InvalidEvent, match="cross-list category may not be added"):
        _add_secondary("cs.AI").validate_pre_lock(
            _sub(GENERAL_PRIMARY, [SECONDARY]))


def test_add_secondary_ok_when_primary_is_specific():
    _add_secondary(SECONDARY).validate_pre_lock(_sub(SPECIFIC_PRIMARY))  # no raise


def test_add_secondary_replacement_is_exempt():
    """version > 1 is exempt (edge case 1)."""
    _add_secondary("cs.AI").validate_pre_lock(
        _sub(GENERAL_PRIMARY, [SECONDARY], version=2))  # no raise


# --- not stuck ---

def test_not_stuck_can_recover_from_general_primary_with_secondary():
    """A submission that somehow holds a general primary with a secondary is
    recoverable: removing the secondary is not blocked, and the primary can
    then be changed. The user is never trapped."""
    stuck = _sub(GENERAL_PRIMARY, [SECONDARY])
    after_remove = _remove_secondary(SECONDARY).apply(stuck)
    assert after_remove.secondary_categories == []
    # With the secondary gone, changing the primary is allowed again.
    _set_primary(SPECIFIC_PRIMARY).validate_pre_lock(after_remove)  # no raise
