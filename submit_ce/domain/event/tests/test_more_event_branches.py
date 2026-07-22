"""
Focused branch tests for the event domain.

The event module is large and has many validation branches. This file contains
additional unit tests for the event domain.

Design notes
------------
- Use the package-level 'make_event' alias for factory-based creation.
- Each test exercises *one* validation idea. When possible, we check both the
  “reject” and the “accept” path for clarity.
"""

# Use same style as existing tests.
from datetime import datetime
from pytz import UTC

# Core domain models used by these tests.
from submit_ce.domain import submission as submod, meta, agent

# Event classes (and exception) we target for branch coverage.
from submit_ce.domain.event import (
    SetTitle,
    SetAbstract,
    SetLicense,
    RemoveSecondaryClassification,
    FinalizeSubmission,
    InvalidEvent,
)

import pytest


# -----------------------------
# Test utilities (tiny helpers)
# -----------------------------

# Return a timezone-aware 'now'.
def _now():
    # Using pytz.UTC.
    return datetime.now(UTC)


# Construct a minimal PublicUser acceptable to the domain.
def _user(uid: str = "u1"):
    # PublicUser requires name, user_id, email; endorsements defaults to [].
    return agent.PublicUser(
        name="Test User",
        user_id=uid,
        email=f"{uid}@example.org",
        endorsements=[],
    )


# Construct a minimal Submission used by most tests below.
def _blank_submission(uid: str = "u1"):
    u = _user(uid)
    return submod.Submission(
        creator=u,
        owner=u,
        created=_now(),
    )


# -------------------------------------------------------
# Tests: small, focused validations in event/__init__.py
# -------------------------------------------------------

def test_set_title_accepts_all_caps():
    """
    SetTitle no longer rejects titles that are entirely uppercase.

    Why: qa's TitleIsValid excessive-capitalization check is advisory (WARN),
    not blocking; only an empty/missing title raises InvalidEvent now.
    """
    s = _blank_submission()
    e = SetTitle(creator=s.creator, title="ALL CAPS TITLE")
    e.validate_pre_lock(s)


def test_set_title_rejects_trailing_period():
    """
    SetTitle should reject titles ending with a trailing period.

    Why: Title validation includes a "no trailing '.'" rule.
    Expectation: InvalidEvent is raised by .validate_pre_lock(submission).
    """
    s = _blank_submission()
    e = SetTitle(creator=s.creator, title="Ends with period.")
    with pytest.raises(InvalidEvent):
        e.validate_pre_lock(s)


def test_set_abstract_length_bounds_both_paths():
    """
    SetAbstract length rules: too short and reasonable-length abstracts both accept.

    Why: qa's AbstractIsValid length check (NotTooShort/NotTooLong) is advisory
    (WARN), not blocking; only an empty/missing abstract raises InvalidEvent now.
    """
    s = _blank_submission()

    e_short = SetAbstract(creator=s.creator, abstract="too short")
    e_short.validate_pre_lock(s)

    ok_text = "This abstract is valid length."
    e_ok = SetAbstract(creator=s.creator, abstract=ok_text)
    e_ok.validate_pre_lock(s)  # no exception means the branch was accepted


def test_set_license_rejects_invalid_uri():
    """
    SetLicense should reject license URIs not present in the allowed set.

    Why: The validator cross-checks the URI against the current LICENSES list.
    Expectation: InvalidEvent is raised by .validate_pre_lock(submission).
    """
    s = _blank_submission()
    e = SetLicense(creator=s.creator, license_uri="http://not-on-our-list")
    with pytest.raises(InvalidEvent):
        e.validate_pre_lock(s)


def test_abstract_accepts_when_not_capitalized():
    """
    qa's AbstractIsValid lowercase-start check is advisory (WARN), not blocking.
    """
    s = _blank_submission()
    e = SetAbstract(creator=s.creator, abstract="not capitalized first sentence.")
    e.validate_pre_lock(s)


def test_abstract_accepts_when_too_long():
    """
    qa's AbstractIsValid length check is advisory (WARN), not blocking.
    """
    s = _blank_submission()
    too_long = "A" + ("x" * 2000)
    e = SetAbstract(creator=s.creator, abstract=too_long)
    e.validate_pre_lock(s)


def test_remove_secondary_requires_existing_category_then_accepts():
    """
    RemoveSecondaryClassification requires the category to already be present.

    Why: Validation checks that the category exists among secondary classifications.
    Expectation:
      - When missing: InvalidEvent
      - After adding: validate() does not raise
    """
    s = _blank_submission()

    # Missing category -> should raise
    e_missing = RemoveSecondaryClassification(creator=s.creator, category="cond-mat.dis-nn")
    with pytest.raises(InvalidEvent):
        e_missing.validate_pre_lock(s)

    # Add the category, then validate again -> should pass
    s.secondary_classification.append(meta.Classification("cond-mat.dis-nn"))
    e_present = RemoveSecondaryClassification(creator=s.creator, category="cond-mat.dis-nn")
    e_present.validate_pre_lock(s)


def test_finalize_submission_missing_required_fields():
    """
    FinalizeSubmission must see required fields populated on the Submission.

    Why: FinalizeSubmission.validate checks multiple required properties.
    Expectation: On a bare/minimal Submission, validate/apply should raise InvalidEvent.
    """
    s = _blank_submission()
    e = FinalizeSubmission(creator=s.creator, created=_now())
    with pytest.raises(InvalidEvent):
        e.apply(s)  # .apply() triggers .validate_pre_lock() internally

