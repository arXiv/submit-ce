"""Exceptions raised during event handling."""

from qa.checks.models import OnFailurePolicy, Result
from submit_ce.domain.event.base import Event


class InvalidEvent(ValueError):
    """Raised when an invalid event is encountered."""

    def __init__(
        self, event: Event, message: str = "", check_result: Result | None = None
    ) -> None:
        """Use the :class:`.Event` to build an error message."""
        self.event = event
        self.message = message
        self.check_result = check_result
        if not self.message and self.check_result is not None:
            if self.check_result.results:
                reject_messages = [
                    r.message
                    for r in self.check_result.results
                    if r.message and r.check_config.get("on_failure_policy") == OnFailurePolicy.REJECT
                ]
                self.message = f"{self.check_result.message}: {', '.join(reject_messages)}"
            else:
                self.message = self.check_result.message

        r = f"Invalid {event.event_type}: {self.message}"
        super(InvalidEvent, self).__init__(r)


class NoSuchSubmission(RuntimeError):
    """An operation was performed on/for a submission that does not exist."""


class SaveError(RuntimeError):
    """Failed to persist event state."""


class NothingToDo(RuntimeError):
    """There is nothing to do."""
