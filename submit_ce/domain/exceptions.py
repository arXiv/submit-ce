"""Exceptions raised during event handling."""

from arxiv.metadata.metacheck import MetadataCheckReport, complaint2str
from submit_ce.domain.event.base import Event



class InvalidEvent(ValueError):
    """Raised when an invalid event is encountered."""

    def __init__(self, event: Event, message: str = '', report: MetadataCheckReport | None = None) -> None:
        """Use the :class:`.Event` to build an error message."""
        self.event = event
        self.message = message
        self.report = report
        if not self.message and self.report is not None:
            self.message = ", ".join([complaint2str(com) for com in report.complaints])

        r = f"Invalid {event.event_type}: {self.message}"
        super(InvalidEvent, self).__init__(r)


class NoSuchSubmission(RuntimeError):
    """An operation was performed on/for a submission that does not exist."""


class SaveError(RuntimeError):
    """Failed to persist event state."""


class SubmissionLocked(RuntimeError):
    """The submission row is locked by another in-flight operation.

    Intentionally NOT a subclass of `SaveError` so that the existing
    `except SaveError` handlers in UI controllers do not swallow it
    and convert it into HTTP 500. A dedicated Flask error handler
    surfaces this as HTTP 409.
    """

    def __init__(self, submission_id: int | str | None = None) -> None:
        self.submission_id = submission_id
        super().__init__(
            f"submission {submission_id} is locked by another operation"
        )


class NothingToDo(RuntimeError):
    """There is nothing to do."""
