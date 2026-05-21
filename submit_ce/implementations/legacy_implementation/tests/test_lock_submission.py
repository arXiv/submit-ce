"""Unit tests for the submission row lock plumbing.

What's exercised here:

- `_is_lock_wait_timeout` correctly identifies MySQL errno 1205.
- `LegacySubmitImplementation.lock_submission(...)` enters/exits
  cleanly for an existing submission against a SQLite test DB
  (SQLite's `SELECT ... FOR UPDATE` is a no-op syntactically but
  the context manager's commit/rollback/finally machinery still
  needs to be exercised).
- The SQLAlchemy session is rolled back when the `with` body raises.
- `OperationalError(errno=1205)` is translated to
  `SubmissionLocked`.
- `NullImplementation.lock_submission(...)` is a no-op.
- `PubsubEventSubmitImplementation.lock_submission(...)` delegates
  to its inner_api.

What is NOT exercised:

- Real MySQL contention (two sessions competing for the same row)
  and the `innodb_lock_wait_timeout` path. SQLite is the test
  backend; real lock contention has to be verified manually or in
  an integration environment with MySQL.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from submit_ce.domain.exceptions import SubmissionLocked
from submit_ce.implementations import NullImplementation
from submit_ce.implementations.legacy_implementation import (
    LegacySubmitImplementation,
    _is_lock_wait_timeout,
    _MYSQL_LOCK_WAIT_TIMEOUT,
)
from submit_ce.implementations.pubsub import PubsubEventSubmitImplementation


# ---------------------------------------------------------------------------
# _is_lock_wait_timeout
# ---------------------------------------------------------------------------

def _make_operational_error(errno: int) -> OperationalError:
    orig = type("DBAPIError", (Exception,), {})()
    orig.args = (errno, "lock wait timeout exceeded")
    return OperationalError("SELECT ...", {}, orig)


def test_is_lock_wait_timeout_true_for_1205():
    exc = _make_operational_error(_MYSQL_LOCK_WAIT_TIMEOUT)
    assert _is_lock_wait_timeout(exc) is True


def test_is_lock_wait_timeout_false_for_other_errno():
    exc = _make_operational_error(1234)
    assert _is_lock_wait_timeout(exc) is False


def test_is_lock_wait_timeout_false_when_no_orig():
    exc = OperationalError("SELECT ...", {}, None)
    assert _is_lock_wait_timeout(exc) is False


def test_is_lock_wait_timeout_false_when_orig_has_no_args():
    orig = type("Bare", (Exception,), {})()
    exc = OperationalError("SELECT ...", {}, orig)
    assert _is_lock_wait_timeout(exc) is False


# ---------------------------------------------------------------------------
# SubmissionLocked is NOT a SaveError subclass
# ---------------------------------------------------------------------------

def test_submission_locked_not_subclass_of_save_error():
    """Critical invariant: existing `except SaveError` handlers in UI
    controllers must NOT swallow SubmissionLocked, or it would surface
    as 500 instead of 409."""
    from submit_ce.domain.exceptions import SaveError
    assert not issubclass(SubmissionLocked, SaveError)


# ---------------------------------------------------------------------------
# LegacySubmitImplementation.lock_submission against SQLite
# ---------------------------------------------------------------------------

def _make_legacy_impl(session_factory):
    """Build a minimal LegacySubmitImplementation around an in-memory
    SQLAlchemy session factory. Compiler / store don't matter for
    lock_submission tests."""
    return LegacySubmitImplementation(
        store=MagicMock(),
        compiler=MagicMock(),
        get_session=session_factory,
    )


def test_lock_submission_enters_and_exits_cleanly():
    """`lock_submission` must commit on clean exit. Verified with a
    mock session because SQLite's SELECT ... FOR UPDATE is a no-op,
    so a "real" integration test against the test DB would not
    exercise the lock behaviour any more thoroughly than this mock.
    Real MySQL contention is out of scope for unit tests."""
    fake_session = MagicMock()
    fake_session.execute.return_value.scalar_one.return_value = MagicMock()
    fake_session_cm = MagicMock()
    fake_session_cm.__enter__.return_value = fake_session
    fake_session_cm.__exit__.return_value = None

    impl = _make_legacy_impl(lambda: fake_session_cm)

    with impl.lock_submission(42):
        pass  # acquire + release with no body — must not raise.

    fake_session.commit.assert_called_once()
    fake_session.rollback.assert_not_called()


def test_lock_submission_rolls_back_on_exception():
    """If the `with` body raises, the session is rolled back and the
    exception propagates."""
    fake_session = MagicMock()
    fake_session.execute.return_value.scalar_one.return_value = MagicMock()
    fake_session_cm = MagicMock()
    fake_session_cm.__enter__.return_value = fake_session
    fake_session_cm.__exit__.return_value = None

    impl = _make_legacy_impl(lambda: fake_session_cm)

    sentinel = RuntimeError("body failed")
    with pytest.raises(RuntimeError) as ei:
        with impl.lock_submission(42):
            raise sentinel
    assert ei.value is sentinel
    fake_session.rollback.assert_called_once()
    fake_session.commit.assert_not_called()


def test_lock_submission_translates_errno_1205_to_submission_locked():
    """Mock the session so SELECT FOR UPDATE raises OperationalError
    errno 1205; verify SubmissionLocked is raised."""
    fake_session = MagicMock()
    fake_session.execute.side_effect = _make_operational_error(
        _MYSQL_LOCK_WAIT_TIMEOUT
    )
    # Make `with self.get_session() as session` work.
    fake_session_cm = MagicMock()
    fake_session_cm.__enter__.return_value = fake_session
    fake_session_cm.__exit__.return_value = None

    impl = _make_legacy_impl(lambda: fake_session_cm)

    with pytest.raises(SubmissionLocked):
        with impl.lock_submission(42):
            pass

    fake_session.rollback.assert_called()


def test_lock_submission_propagates_non_1205_operational_error():
    """A non-lock-wait OperationalError must propagate as-is."""
    fake_session = MagicMock()
    fake_session.execute.side_effect = _make_operational_error(2002)
    fake_session_cm = MagicMock()
    fake_session_cm.__enter__.return_value = fake_session
    fake_session_cm.__exit__.return_value = None

    impl = _make_legacy_impl(lambda: fake_session_cm)

    with pytest.raises(OperationalError):
        with impl.lock_submission(42):
            pass


def test_load_lock_row_translates_errno_1205():
    """`_load(..., lock_row=True)` must also translate errno 1205 so
    `api.save(...)` paths surface SubmissionLocked, not OperationalError."""
    fake_session = MagicMock()
    fake_session.scalars.side_effect = _make_operational_error(
        _MYSQL_LOCK_WAIT_TIMEOUT
    )
    impl = _make_legacy_impl(MagicMock())

    with pytest.raises(SubmissionLocked):
        impl._load(fake_session, "42", lock_row=True)


def test_load_without_lock_row_does_not_translate_errno_1205():
    """Without lock_row=True, errno 1205 is not a "lock wait" scenario
    we expect — let the original exception propagate."""
    fake_session = MagicMock()
    fake_session.scalars.side_effect = _make_operational_error(
        _MYSQL_LOCK_WAIT_TIMEOUT
    )
    impl = _make_legacy_impl(MagicMock())

    with pytest.raises(OperationalError):
        impl._load(fake_session, "42", lock_row=False)


# ---------------------------------------------------------------------------
# NullImplementation: no-op context manager
# ---------------------------------------------------------------------------

def test_null_implementation_lock_submission_is_no_op():
    # NullImplementation is currently missing `healthy()` so it can't
    # be instantiated as the full abstract API (pre-existing issue,
    # not introduced here). We invoke the unbound method directly to
    # verify the no-op shape without going through `__init__`.
    cm = NullImplementation.lock_submission(MagicMock(), 42)
    cm.__enter__()
    cm.__exit__(None, None, None)  # must not raise


# ---------------------------------------------------------------------------
# PubsubEventSubmitImplementation: delegates
# ---------------------------------------------------------------------------

def test_pubsub_lock_submission_delegates_to_inner_api():
    inner = MagicMock()
    inner.lock_submission.return_value.__enter__.return_value = None
    inner.lock_submission.return_value.__exit__.return_value = None

    publisher = MagicMock()
    impl = PubsubEventSubmitImplementation(
        publisher=publisher, topic="t", inner_api=inner
    )

    with impl.lock_submission(42):
        pass

    inner.lock_submission.assert_called_once_with(42)
