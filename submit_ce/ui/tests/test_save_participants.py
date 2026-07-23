"""Tests for `SaveParticipant` phases fired by ``SubmitApi.save()``.

These tests exercise the real ``FlaskSubmitImplementation`` save path (via the
``app`` fixture) using throw-away participants and side-effect events, in the
style of ``test_save_validate_under_lock.py``. Participants are injected by
mutating ``current_app.api.participants``; the ``app`` fixture is
function-scoped so this does not leak between tests.
"""
from typing import List, Optional, Tuple

import pytest
from flask import current_app

from submit_ce.api.save_participant import (SaveContext, SaveFailure,
                                            SaveParticipant, SavePhase)
from submit_ce.domain.agent import InternalClient
from submit_ce.domain.event.base import Event, EventWithSideEffect
from submit_ce.domain.event.legacy import Withdraw
from submit_ce.domain.exceptions import InvalidEvent


class _Boom(RuntimeError):
    """Distinct exception so tests can assert the original error propagates."""


class _RollbackBoom(RuntimeError):
    """Simulates the DB connection dropping so ``session.rollback()`` itself
    raises during save()'s except handler (PR #82 review finding #1)."""


class _ProbeParticipant(SaveParticipant):
    """Records ``(phase, participant_name)`` calls into a shared list.

    ``raise_in`` makes the named phase raise `_Boom`. ``failures`` collects
    the `SaveFailure` passed to ``on_save_failed``.
    """

    def __init__(self, name: str, calls: List[Tuple[str, str]],
                 raise_in: Optional[str] = None):
        self.name = name
        self.calls = calls
        self.raise_in = raise_in
        self.failures: List[SaveFailure] = []
        self.ctx_snapshots: List[dict] = []

    def _fire(self, phase: str) -> None:
        self.calls.append((phase, self.name))
        if self.raise_in == phase:
            raise _Boom(f"{self.name} raised in {phase}")

    def under_lock(self, ctx: SaveContext) -> None:
        self._fire("under_lock")

    def before_commit(self, ctx: SaveContext) -> None:
        self.ctx_snapshots.append({
            "after": ctx.after,
            "committed": list(ctx.committed),
        })
        self._fire("before_commit")

    def after_commit(self, ctx: SaveContext) -> None:
        self._fire("after_commit")

    def on_save_failed(self, ctx: SaveContext, failure: SaveFailure) -> None:
        self.failures.append(failure)
        self._fire("on_save_failed")


class _ProbeSideEffect(EventWithSideEffect):
    """Side-effect event that records calls and can raise under the lock."""

    NAME = "probe side effect"
    NAMED = "probe side effect"

    should_block: bool = False
    calls: List[str] = []

    def validate_pre_lock(self, submission) -> None:
        pass

    def validate_under_lock(self, api, submission) -> None:
        self.calls.append("validate_under_lock")
        if self.should_block:
            raise InvalidEvent(self, "blocked under lock")

    def execute(self, api, submission) -> None:
        self.calls.append("execute")

    def project(self, submission):
        return submission


class _UndeclaredConsequence(Event):
    """A plain no-op event, used only as an undeclared consequence type."""

    NAME = "undeclared consequence"
    NAMED = "undeclared consequence"

    def validate_pre_lock(self, submission) -> None:
        pass

    def project(self, submission):
        return submission


class _ProbeEmitsUndeclaredConsequence(Event):
    """An event whose `consequences()` returns a type missing from its own
    `CONSEQUENCE_TYPES` — i.e. it violates the declared-consequence contract
    that `Event.get_consequences()` enforces at runtime."""

    NAME = "probe emits undeclared consequence"
    NAMED = "probe emits undeclared consequence"

    # Deliberately does NOT declare _UndeclaredConsequence.
    CONSEQUENCE_TYPES = frozenset()

    def validate_pre_lock(self, submission) -> None:
        pass

    def project(self, submission):
        return submission

    def consequences(self, submission):
        return [_UndeclaredConsequence(creator=self.creator, client=self.client)]


def _client() -> InternalClient:
    return InternalClient(name="test_save_participants")


def _enlist(*participants: SaveParticipant) -> None:
    current_app.api.participants = list(participants)


def test_phase_ordering_two_participants(app, authorized_user, sub_created):
    """under_lock in list order; before_commit/after_commit in reverse order,
    with event work in between; the event is committed."""
    with app.app_context():
        sid = str(sub_created.submission_id)
        _, history_before = current_app.api.get_with_history(sid)

        calls: List[Tuple[str, str]] = []
        a = _ProbeParticipant("a", calls)
        b = _ProbeParticipant("b", calls)
        _enlist(a, b)

        probe = _ProbeSideEffect(creator=authorized_user, client=_client(), calls=[])
        current_app.api.save(probe, submission_id=sid)

        assert calls == [
            ("under_lock", "a"), ("under_lock", "b"),
            ("before_commit", "b"), ("before_commit", "a"),
            ("after_commit", "b"), ("after_commit", "a"),
        ]
        # Event work happened between under_lock and before_commit.
        assert probe.calls == ["validate_under_lock", "execute"]
        _, history_after = current_app.api.get_with_history(sid)
        assert len(history_after) == len(history_before) + 1


def test_under_lock_raise_aborts_cleanly(app, authorized_user, sub_created):
    """Raising in under_lock is the clean abort: no event ran, nothing
    committed, on_save_failed fires with the participant phase and identity."""
    with app.app_context():
        sid = str(sub_created.submission_id)
        _, history_before = current_app.api.get_with_history(sid)

        calls: List[Tuple[str, str]] = []
        a = _ProbeParticipant("a", calls)
        b = _ProbeParticipant("b", calls, raise_in="under_lock")
        _enlist(a, b)

        probe = _ProbeSideEffect(creator=authorized_user, client=_client(), calls=[])
        with pytest.raises(_Boom):
            current_app.api.save(probe, submission_id=sid)

        assert probe.calls == []  # no event validated or executed
        assert calls == [
            ("under_lock", "a"), ("under_lock", "b"),
            ("on_save_failed", "b"), ("on_save_failed", "a"),  # reverse order
        ]
        failure = a.failures[0]
        assert failure.phase == SavePhase.PARTICIPANT_UNDER_LOCK
        assert failure.participant is b
        assert failure.event is None
        assert isinstance(failure.exc, _Boom)

        _, history_after = current_app.api.get_with_history(sid)
        assert len(history_after) == len(history_before)


def test_before_commit_raise_rolls_back_db(app, authorized_user, sub_created):
    """Raising in before_commit rolls the DB back — but the event's side
    effects already ran (the documented validate_under_lock-style caveat)."""
    with app.app_context():
        sid = str(sub_created.submission_id)
        _, history_before = current_app.api.get_with_history(sid)

        calls: List[Tuple[str, str]] = []
        a = _ProbeParticipant("a", calls, raise_in="before_commit")
        _enlist(a)

        probe = _ProbeSideEffect(creator=authorized_user, client=_client(), calls=[])
        with pytest.raises(_Boom):
            current_app.api.save(probe, submission_id=sid)

        # The side effects DID run; only the DB write was rolled back.
        assert probe.calls == ["validate_under_lock", "execute"]
        failure = a.failures[0]
        assert failure.phase == SavePhase.PARTICIPANT_BEFORE_COMMIT
        assert failure.participant is a

        _, history_after = current_app.api.get_with_history(sid)
        assert len(history_after) == len(history_before)


def test_event_validate_under_lock_failure_reported(app, authorized_user, sub_created):
    """An event rejected under the lock reaches on_save_failed with the event
    phase and the event itself; InvalidEvent propagates unchanged."""
    with app.app_context():
        sid = str(sub_created.submission_id)
        calls: List[Tuple[str, str]] = []
        a = _ProbeParticipant("a", calls)
        _enlist(a)

        probe = _ProbeSideEffect(creator=authorized_user, client=_client(),
                                 should_block=True, calls=[])
        with pytest.raises(InvalidEvent):
            current_app.api.save(probe, submission_id=sid)

        failure = a.failures[0]
        assert failure.phase == SavePhase.EVENT_VALIDATE_UNDER_LOCK
        assert failure.event is probe
        assert failure.participant is None
        assert isinstance(failure.exc, InvalidEvent)


def test_event_consequences_failure_reported(app, authorized_user, sub_created):
    """`Event.get_consequences()` raises `RuntimeError` when an event returns
    a consequence type it did not declare in `CONSEQUENCE_TYPES` (the runtime
    check in `Event.get_consequences`, domain/event/base.py:196-200). The save
    loop must report this as `SavePhase.EVENT_CONSEQUENCES`, name the
    offending event, and roll back — including the parent event's own write,
    even though it was persisted earlier in the same transaction."""
    with app.app_context():
        sid = str(sub_created.submission_id)
        _, history_before = current_app.api.get_with_history(sid)

        calls: List[Tuple[str, str]] = []
        a = _ProbeParticipant("a", calls)
        _enlist(a)

        probe = _ProbeEmitsUndeclaredConsequence(creator=authorized_user, client=_client())
        with pytest.raises(RuntimeError, match="undeclared consequence"):
            current_app.api.save(probe, submission_id=sid)

        failure = a.failures[0]
        assert failure.phase == SavePhase.EVENT_CONSEQUENCES
        assert failure.event is probe
        assert failure.participant is None
        assert isinstance(failure.exc, RuntimeError)

        # The parent event's own persisted write is rolled back too, even
        # though get_consequences() raised after store_event() ran.
        _, history_after = current_app.api.get_with_history(sid)
        assert len(history_after) == len(history_before)


def test_after_commit_raise_is_swallowed(app, authorized_user, sub_created):
    """The save already committed: an after_commit failure is logged and
    swallowed, save() returns normally and on_save_failed does NOT fire."""
    with app.app_context():
        sid = str(sub_created.submission_id)
        _, history_before = current_app.api.get_with_history(sid)

        calls: List[Tuple[str, str]] = []
        a = _ProbeParticipant("a", calls, raise_in="after_commit")
        _enlist(a)

        probe = _ProbeSideEffect(creator=authorized_user, client=_client(), calls=[])
        current_app.api.save(probe, submission_id=sid)  # must not raise

        assert a.failures == []  # no rollback happened
        assert ("on_save_failed", "a") not in calls
        _, history_after = current_app.api.get_with_history(sid)
        assert len(history_after) == len(history_before) + 1


def test_on_save_failed_raise_never_masks_original(app, authorized_user, sub_created):
    """A participant blowing up in on_save_failed is logged; the other
    participants are still notified and the ORIGINAL exception propagates."""
    with app.app_context():
        sid = str(sub_created.submission_id)
        calls: List[Tuple[str, str]] = []
        a = _ProbeParticipant("a", calls)
        b = _ProbeParticipant("b", calls, raise_in="on_save_failed")
        _enlist(a, b)

        probe = _ProbeSideEffect(creator=authorized_user, client=_client(),
                                 should_block=True, calls=[])
        with pytest.raises(InvalidEvent):  # original, not b's _Boom
            current_app.api.save(probe, submission_id=sid)

        # b raised in on_save_failed, but a was still notified after it.
        assert ("on_save_failed", "b") in calls
        assert ("on_save_failed", "a") in calls
        assert calls.index(("on_save_failed", "b")) < calls.index(("on_save_failed", "a"))


def test_rollback_failure_keeps_original_error_and_fires_participants(
        app, authorized_user, sub_created, monkeypatch):
    """PR #82 review: if the save fails AND ``session.rollback()`` then
    raises (e.g. the DB connection dropped mid-transaction), save() must still

      (a) propagate the ORIGINAL failure, not the rollback error,
      (b) fire ``on_save_failed`` so audit/notification participants are not
          silently skipped on exactly the DB-failure case they exist to catch,
          and
      (c) tell those participants the rollback did not succeed, via
          ``SaveFailure.rolledback``, so they know the DB state is unknown.
    """
    with app.app_context():
        sid = str(sub_created.submission_id)

        calls: List[Tuple[str, str]] = []
        recorder = _ProbeParticipant("recorder", calls)
        # `trigger` supplies the ORIGINAL failure, from inside the locked txn.
        trigger = _ProbeParticipant("trigger", calls, raise_in="under_lock")
        _enlist(recorder, trigger)

        api = current_app.api
        real_get_session = api.get_session

        def get_session_with_failing_rollback():
            session = real_get_session()

            def boom_rollback(*args, **kwargs):
                raise _RollbackBoom("connection dropped during rollback")

            session.rollback = boom_rollback
            return session

        monkeypatch.setattr(api, "get_session",
                            get_session_with_failing_rollback)

        probe = _ProbeSideEffect(creator=authorized_user, client=_client(), calls=[])
        # The caller must see the real cause, not the rollback failure.
        with pytest.raises(_Boom):
            api.save(probe, submission_id=sid)

        # on_save_failed must still fire despite rollback() raising.
        assert ("on_save_failed", "recorder") in calls
        assert recorder.failures, "on_save_failed participant was never notified"
        assert isinstance(recorder.failures[0].exc, _Boom)
        # The failed rollback is signalled so participants know DB state is unknown.
        assert recorder.failures[0].rolledback is False


def test_before_commit_sees_final_state(app, authorized_user, sub_created):
    """By before_commit the context carries the projected state and the
    committed events of this save."""
    with app.app_context():
        sid = str(sub_created.submission_id)
        calls: List[Tuple[str, str]] = []
        a = _ProbeParticipant("a", calls)
        _enlist(a)

        probe = _ProbeSideEffect(creator=authorized_user, client=_client(), calls=[])
        current_app.api.save(probe, submission_id=sid)

        snapshot = a.ctx_snapshots[0]
        assert snapshot["after"] is not None
        assert len(snapshot["committed"]) >= 1


def test_withdraw_path_fires_participants(app, authorized_user,
                                          published_submission, mocker):
    """The Withdraw branch of save() is a separate code path from _save; it
    must fire the same participant phases."""
    with app.app_context():
        _, paper_id = published_submission
        # The app fixture uses a NullFileStore whose write methods raise by
        # design; Withdraw.execute writes the `withdrawn` source file.
        mocker.patch.object(current_app.api.store, "delete_all_source_files")
        mocker.patch.object(current_app.api.store, "store_source_file")

        calls: List[Tuple[str, str]] = []
        a = _ProbeParticipant("a", calls)
        _enlist(a)

        cmd = Withdraw(creator=authorized_user, client=_client(),
                       paper_id=paper_id,
                       comment="Withdrawn because of a fatal flaw in section 3.",
                       abstract="This paper has been withdrawn by the authors.")
        submission, committed = current_app.api.save(cmd)

        assert calls == [
            ("under_lock", "a"),
            ("before_commit", "a"),
            ("after_commit", "a"),
        ]
        snapshot = a.ctx_snapshots[0]
        assert snapshot["after"] is not None
        assert len(snapshot["committed"]) == 1
