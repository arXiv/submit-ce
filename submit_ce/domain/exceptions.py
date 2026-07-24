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


class NoSuchDocument(RuntimeError):
    """An operation referenced an arXiv paper (document) that does not exist."""


class SaveError(RuntimeError):
    """Failed to persist event state."""


class NothingToDo(RuntimeError):
    """There is nothing to do."""
