"""Unit tests for AdminRemove and UnRemove events (SUBMISSION-257)."""
from datetime import datetime
from pytz import UTC
import pytest

from submit_ce.domain import submission as submod, agent
from submit_ce.domain.submission import Submission
from submit_ce.domain.event import AdminRemove, UnRemove, InvalidEvent


def _now():
    return datetime.now(UTC)


def _user(uid="u1"):
    return agent.PublicUser(name="Test User", user_id=uid,
                            email=f"{uid}@example.org", endorsements=[])


def _submitted_submission(uid="u1"):
    u = _user(uid)
    s = submod.Submission(creator=u, owner=u, created=_now())
    s.status = Submission.SUBMITTED
    return s


def _announced_submission(uid="u1", arxiv_id="2501.01234"):
    u = _user(uid)
    s = submod.Submission(creator=u, owner=u, created=_now())
    s.status = Submission.ANNOUNCED
    s.arxiv_id = arxiv_id
    return s


def test_admin_remove_sets_removed():
    s = _submitted_submission()
    e = AdminRemove(creator=s.creator, created=_now())
    e.validate_pre_lock(s)
    after = e.apply(s)
    assert after.status == Submission.REMOVED
    assert after.is_removed
    assert not after.is_active


def test_admin_remove_rejects_announced():
    s = _announced_submission()
    e = AdminRemove(creator=s.creator, created=_now())
    with pytest.raises(InvalidEvent):
        e.validate_pre_lock(s)


def test_admin_remove_rejects_already_removed():
    s = _submitted_submission()
    s.status = Submission.REMOVED
    e = AdminRemove(creator=s.creator, created=_now())
    with pytest.raises(InvalidEvent):
        e.validate_pre_lock(s)


def test_unremove_sets_on_hold():
    s = _submitted_submission()
    s.status = Submission.REMOVED
    e = UnRemove(creator=s.creator, created=_now())
    e.validate_pre_lock(s)
    after = e.apply(s)
    assert after.status == Submission.SUBMITTED
    assert after.is_on_hold
    assert not after.is_removed


def test_unremove_rejects_when_not_removed():
    s = _submitted_submission()
    e = UnRemove(creator=s.creator, created=_now())
    with pytest.raises(InvalidEvent):
        e.validate_pre_lock(s)


def test_remove_then_unremove_roundtrip():
    s = _submitted_submission()
    s = AdminRemove(creator=s.creator, created=_now()).apply(s)
    assert s.is_removed
    s = UnRemove(creator=s.creator, created=_now()).apply(s)
    assert s.is_on_hold and not s.is_removed
