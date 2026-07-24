"""Tests for :func:`submit_ce.domain.event.validators.passes_qa_checks`.

These tests construct :class:`qa.checks.models.Result` objects directly,
rather than exercising real qa checks against real-world strings. That
keeps this coverage independent of how any individual qa sub-check's
``on_failure_policy`` happens to be configured upstream: submit-ce only
needs to guarantee how it reacts to a given disposition, not which real
input strings currently produce which disposition (that's qa's own
responsibility to test).
"""
from qa.checks.models import Disposition, OnFailurePolicy, Result

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


def _sub_result(policy: OnFailurePolicy, message: str) -> Result:
    """A failing sub-check result, as would appear in Result.results."""
    return Result(
        check_config={"on_failure_policy": policy},
        passed=False,
        disposition=Disposition.WARN if policy == OnFailurePolicy.WARN else Disposition.REJECT,
        message=message,
    )


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
        results=[_sub_result(OnFailurePolicy.WARN, "Excessive capitalization.")],
    )
    validators.passes_qa_checks(_event(), result)  # should not raise


def test_none_does_not_raise():
    validators.passes_qa_checks(_event(), None)  # should not raise


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
    try:
        validators.passes_qa_checks(_event(), result)
        assert False, "expected InvalidEvent to be raised"
    except InvalidEvent as e:
        assert e.message == "Title is invalid or empty."


def test_reject_disposition_message_ignores_sub_results():
    """The exception message is always the aggregate's own message; the
    content of check_result.results does not affect it."""
    result = Result(
        check_config={},
        passed=False,
        disposition=Disposition.REJECT,
        message="Title is invalid or empty.",
        results=[
            _sub_result(OnFailurePolicy.REJECT, "Cannot be empty."),
            _sub_result(OnFailurePolicy.WARN, "Excessive capitalization."),
        ],
    )
    try:
        validators.passes_qa_checks(_event(), result)
        assert False, "expected InvalidEvent to be raised"
    except InvalidEvent as e:
        assert e.message == "Title is invalid or empty."
