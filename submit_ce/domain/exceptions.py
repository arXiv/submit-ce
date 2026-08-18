"""Exceptions raised during event handling."""

from submit_ce.domain.event.base import Event


class InvalidEvent(ValueError):
    """Raised when an invalid event is encountered."""

    def __init__(
        self, event: Event, message: str = "") -> None:
        """Use the :class:`.Event` to build an error message."""
        self.event = event
        self.message = message

        r = f"Invalid {event.event_type}: {self.message}"
        super(InvalidEvent, self).__init__(r)


class NoSuchSubmission(RuntimeError):
    """An operation was performed on/for a submission that does not exist."""


class NoSuchDocument(RuntimeError):
    """An operation referenced an arXiv paper (document) that does not exist."""


class SaveError(RuntimeError):
    """Failed to persist event state."""


class NothingToDo(RuntimeError):
    """There is nothing to do."""
