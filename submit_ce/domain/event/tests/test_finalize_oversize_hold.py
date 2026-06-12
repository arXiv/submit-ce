"""Unit tests for FinalizeSubmission.consequences() oversize -> hold logic.

These exercise the pure domain method directly, with hand-built submissions,
so no app or file store is needed.
"""

from datetime import datetime

from pytz import UTC

from submit_ce.domain import agent
from submit_ce.domain.meta import Classification
from submit_ce.domain.event import FinalizeSubmission, AddHold
from submit_ce.domain.submission import Submission, Hold, Waiver


def _user():
    return agent.PublicUser(name="Test User", user_id="u1",
                            email="u1@example.org", endorsements=[])


def _submission(is_oversize=False, waivers=None):
    u = _user()
    return Submission(
        creator=u, owner=u, created=datetime.now(UTC),
        primary_classification=Classification(category="astro-ph.GA"),
        is_oversize=is_oversize,
        waivers=waivers or {})


def _finalize():
    return FinalizeSubmission(creator=_user(), created=datetime.now(UTC))


def test_oversize_finalize_yields_addhold():
    events = _finalize().consequences(_submission(is_oversize=True))
    assert len(events) == 1
    hold = events[0]
    assert isinstance(hold, AddHold)
    assert hold.hold_type == Hold.Type.SOURCE_OVERSIZE


def test_not_oversize_finalize_yields_nothing():
    assert _finalize().consequences(_submission(is_oversize=False)) == []


def test_oversize_with_waiver_yields_nothing():
    waiver = Waiver(event_id="w1", created=datetime.now(UTC), creator=_user(),
                    waiver_type=Hold.Type.SOURCE_OVERSIZE, waiver_reason="ok")
    sub = _submission(is_oversize=True, waivers={"w1": waiver})
    assert _finalize().consequences(sub) == []


def test_declared_consequence_type():
    assert FinalizeSubmission.CONSEQUENCE_TYPES == frozenset({AddHold})
