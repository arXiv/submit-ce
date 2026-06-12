"""Runtime behavior of :meth:`Event.get_consequences` (``base.py``).

The *acyclicity* of the consequence graph is covered by
``test_consequences_graph.py``. This module covers what ``get_consequences``
does at runtime.

These use throwaway ``Event`` subclasses defined only for the test. They live
under a ``tests`` package, so the production graph test excludes them from its
acyclicity check.
"""

from datetime import datetime

import pytest
from pytz import UTC

from submit_ce.domain import agent
from submit_ce.domain.event.base import Event


def _user(uid="u1"):
    return agent.PublicUser(name="Test User", user_id=uid,
                            email=f"{uid}@example.org", endorsements=[])


class _Consequence(Event):
    """A throwaway follow-on event."""

    NAME = "test consequence"

    def validate_pre_lock(self, submission):
        pass

    def project(self, submission):
        return submission


class _Cause(Event):
    """A throwaway event that declares and emits a ``_Consequence``."""

    NAME = "test cause"
    CONSEQUENCE_TYPES = frozenset({_Consequence})

    def validate_pre_lock(self, submission):
        pass

    def project(self, submission):
        return submission

    def consequences(self, submission):
        return [_Consequence(creator=self.creator)]


class _Undeclared(Event):
    """Emits a consequence type it did not declare in CONSEQUENCE_TYPES."""

    NAME = "test undeclared"

    def validate_pre_lock(self, submission):
        pass

    def project(self, submission):
        return submission

    def consequences(self, submission):
        return [_Consequence(creator=self.creator)]


def _committed(event_cls, **kw):
    """A committed event instance (``created`` set, so ``event_id`` works)."""
    return event_cls(creator=_user(), created=datetime.now(UTC), **kw)


def test_get_consequences_stamps_cause_with_parent_event_id():
    """Each emitted consequence records the parent's event_id in ``cause``."""
    parent = _committed(_Cause)
    consequences = parent.get_consequences(submission=None)
    assert len(consequences) == 1
    child = consequences[0]
    assert isinstance(child, _Consequence)
    assert child.cause == parent.event_id


def test_get_consequences_default_is_empty():
    """An event that declares nothing emits nothing (and stamps nothing)."""
    parent = _committed(_Consequence)
    assert parent.get_consequences(submission=None) == []


def test_undeclared_consequence_type_raises():
    """Emitting a type absent from CONSEQUENCE_TYPES is a runtime error,
    and the offending consequence is never stamped with a cause."""
    parent = _committed(_Undeclared)
    with pytest.raises(RuntimeError, match="undeclared consequence"):
        parent.get_consequences(submission=None)


def test_get_consequences_on_uncommitted_event_raises():
    """Without ``created`` the parent has no event_id to attribute as cause."""
    parent = _Cause(creator=_user())  # no `created` -> not committed
    with pytest.raises(RuntimeError, match="not yet commited"):
        parent.get_consequences(submission=None)
