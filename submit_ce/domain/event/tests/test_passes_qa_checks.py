"""Tests for :func:`submit_ce.domain.event.validators.passes_qa_checks`.

These tests construct :class:`qa.checks.models.Result` objects directly,
rather than exercising real qa checks against real-world strings. That
keeps this coverage independent of how any individual qa sub-check's
``on_failure_policy`` happens to be configured upstream: submit-ce only
needs to guarantee how it reacts to a given disposition, not which real
input strings currently produce which disposition (that's qa's own
responsibility to test).
"""
import pytest
from qa.checks.models import Disposition, Result

from submit_ce.domain import agent
from submit_ce.domain.event import SetTitle, validators
from submit_ce.domain.exceptions import InvalidEvent

user = agent.PublicUser(
    name="Test User",
    user_id="u1",
    email="u1@example.org",
    endorsements=[],
)


def _event() -> SetTitle:
    """Any Event instance works; passes_qa_checks only needs .event_type."""
    return SetTitle(creator=user, title="A perfectly fine title")


def test_ok_disposition_does_not_raise():
    result = Result(check_config={}, passed=True, disposition=Disposition.OK, message="")
    validators.passes_qa_checks(_event(), result)  # should not raise


def test_warn_disposition_does_not_raise():
    """Per current policy, WARN is advisory and never blocks the event."""
    result = Result(
        check_config={},
        passed=True,
        disposition=Disposition.WARN,
        message="",
        results=[
            Result(check_config={}, passed=False, disposition=Disposition.WARN, message="Excessive capitalization.")
        ],
    )
    validators.passes_qa_checks(_event(), result)  # should not raise


def test_reject_disposition_raises_with_aggregate_message():
    """Mirrors the empty/missing-field path: no sub-results, just the
    aggregate's own failure message."""
    result = Result(
        check_config={},
        passed=False,
        disposition=Disposition.REJECT,
        message="Title is invalid or empty.",
        results=[],
    )
    with pytest.raises(InvalidEvent) as excinfo:
        validators.passes_qa_checks(_event(), result)
    assert excinfo.value.message == "Title is invalid or empty."


def test_reject_disposition_message_includes_only_reject_sub_results():
    """The exception message is built from _messages(REJECT): the
    joined messages of failing sub-results whose own disposition is REJECT,
    excluding WARN-tier sub-results."""
    result = Result(
        check_config={},
        passed=False,
        disposition=Disposition.REJECT,
        message="Title is invalid or empty.",
        results=[
            Result(check_config={}, passed=False, disposition=Disposition.REJECT, message="Cannot be empty."),
            Result(check_config={}, passed=False, disposition=Disposition.WARN, message="Excessive capitalization."),
        ],
    )
    with pytest.raises(InvalidEvent) as excinfo:
        validators.passes_qa_checks(_event(), result)
    assert excinfo.value.message == "Cannot be empty."


def test_reject_disposition_message_joins_multiple_reject_sub_results():
    """Multiple failing REJECT-tier sub-results are newline-joined."""
    result = Result(
        check_config={},
        passed=False,
        disposition=Disposition.REJECT,
        message="Title is invalid or empty.",
        results=[
            Result(check_config={}, passed=False, disposition=Disposition.REJECT, message="Cannot be empty."),
            Result(check_config={}, passed=False, disposition=Disposition.REJECT, message="Must contain letters."),
        ],
    )
    with pytest.raises(InvalidEvent) as excinfo:
        validators.passes_qa_checks(_event(), result)
    assert excinfo.value.message == "Cannot be empty.\nMust contain letters."
