"""Tests that ``validate_under_lock`` is invoked inside ``_save``.

``EventWithSideEffect.validate_under_lock`` is meant to run inside the locked
transaction taken by ``SubmitApi.save()``, immediately before ``execute`` and
while the submission row lock is held. Raising ``InvalidEvent`` from it must
abort the transaction so ``execute`` never runs and nothing is committed.

These tests exercise the real ``FlaskSubmitImplementation`` save path (via the
``app`` fixture and a real ``sub_created`` submission) using throw-away
``EventWithSideEffect`` subclasses defined only for the test.
"""
from typing import List

import pytest
from flask import current_app

from submit_ce.domain.agent import InternalClient
from submit_ce.domain.event.base import EventWithSideEffect
from submit_ce.domain.exceptions import InvalidEvent


class _ProbeSideEffect(EventWithSideEffect):
    """Records the order of ``validate_under_lock``/``execute`` calls.

    ``calls`` is mutated in place by the save machinery (the same instance is
    passed through ``_save``), so the test reads it back off the event object
    after ``save`` returns. Setting ``should_block`` makes
    ``validate_under_lock`` raise, simulating a rejection discovered under the
    lock.
    """

    NAME = "probe side effect"
    NAMED = "probe side effect"

    should_block: bool = False
    calls: List[str] = []

    def validate(self, submission) -> None:
        pass

    def validate_under_lock(self, api, submission) -> None:
        self.calls.append("validate_under_lock")
        if self.should_block:
            raise InvalidEvent(self, "blocked under lock")

    def execute(self, api, submission) -> None:
        self.calls.append("execute")

    def project(self, submission):
        return submission


class _ProbeNoOverride(EventWithSideEffect):
    """A side-effect event that does NOT override ``validate_under_lock``.

    Guards the base-class default (a no-op): ``execute`` must still run.
    """

    NAME = "probe no override"
    NAMED = "probe no override"

    calls: List[str] = []

    def validate(self, submission) -> None:
        pass

    def execute(self, api, submission) -> None:
        self.calls.append("execute")

    def project(self, submission):
        return submission


def _client() -> InternalClient:
    return InternalClient(name="test_save_validate_under_lock")


def test_validate_under_lock_called_before_execute(app, authorized_user, sub_created):
    """``_save`` calls ``validate_under_lock`` and it runs before ``execute``."""
    with app.app_context():
        probe = _ProbeSideEffect(creator=authorized_user, client=_client(), calls=[])
        current_app.api.save(probe, submission_id=str(sub_created.submission_id))

        assert probe.calls == ["validate_under_lock", "execute"]


def test_validate_under_lock_block_aborts_execute_and_rolls_back(
    app, authorized_user, sub_created
):
    """Raising ``InvalidEvent`` under the lock skips ``execute`` and commits nothing."""
    with app.app_context():
        sid = str(sub_created.submission_id)
        _, history_before = current_app.api.get_with_history(sid)

        probe = _ProbeSideEffect(
            creator=authorized_user, client=_client(), should_block=True, calls=[]
        )
        with pytest.raises(InvalidEvent):
            current_app.api.save(probe, submission_id=sid)

        # validate_under_lock ran, execute did not.
        assert probe.calls == ["validate_under_lock"]

        # The transaction was rolled back: no new event was committed.
        _, history_after = current_app.api.get_with_history(sid)
        assert len(history_after) == len(history_before)


def test_default_validate_under_lock_is_noop(app, authorized_user, sub_created):
    """A side-effect event without an override still executes normally."""
    with app.app_context():
        probe = _ProbeNoOverride(creator=authorized_user, client=_client(), calls=[])
        current_app.api.save(probe, submission_id=str(sub_created.submission_id))

        assert probe.calls == ["execute"]
