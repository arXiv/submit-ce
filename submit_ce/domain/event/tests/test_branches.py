# Minimal branch-coverage tests for event creation and validation.

from datetime import datetime
from pytz import UTC
import pytest


from submit_ce.api.domain import submission as submod, agent
from submit_ce.api.domain.event import (
    make_event,              # <- alias to base.event_factory
    FinalizeSubmission,      # used directly to hit validation error
    Announce,                # simple project() path
    InvalidEvent,            # domain exception
)


def _now():
    # Keep consistent with existing tests that use pytz.UTC
    return datetime.now(UTC)


def _user(u="u1"):
    # PublicUser requires: name, user_id, email.
    # endorsements defaults to [] if not provided.
    return agent.PublicUser(
        name="Test User",
        user_id=u,
        email=f"{u}@example.org",
        endorsements=[],
    )


def test_create_submission_round_trip():
    """CreateSubmission via factory; apply(None) creates a new Submission."""
    creator = _user("alice")
    ev = make_event("CreateSubmission", created=_now(), creator=creator)
    after = ev.apply(None)  # special-case: creation works with submission=None
    assert after.creator == creator
    assert after.owner == creator
    # ID may be None pre-persist; just assert it’s stable/typed if present.
    assert after.submission_id is None or isinstance(after.submission_id, int)


def test_finalize_submission_missing_required_fields_raises():
    """FinalizeSubmission should raise when required fields are missing."""
    creator = _user("bob")
    sub = submod.Submission(creator=creator, owner=creator, created=_now())
    ev = FinalizeSubmission(creator=creator, created=_now())
    with pytest.raises(InvalidEvent):
        ev.apply(sub)


def test_announce_sets_status_and_id():
    """Announce.project sets status to ANNOUNCED and arxiv_id to provided value."""
    creator = _user("carol")
    # A minimal submission that is not yet announced
    sub = submod.Submission(creator=creator, owner=creator, created=_now())
    # The versions field is commented out in Submission while Announce appends
    # to it. [FIX ME]
    sub.versions = []

    ev = Announce(creator=creator, created=_now(), arxiv_id="2501.01234")
    after = ev.apply(sub)
    assert after.status == submod.Submission.ANNOUNCED
    assert after.arxiv_id == "2501.01234"


def test_factory_unknown_type_raises_runtime_error():
    """Factory should error with an unknown event type name."""
    with pytest.raises(RuntimeError):
        make_event("NoSuchEventType", created=_now(), creator=_user("dave"))