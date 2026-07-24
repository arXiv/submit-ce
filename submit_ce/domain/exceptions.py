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


class ActiveSubmissionExists(InvalidEvent):
    """A paper already has an in-progress submission that blocks a new one.

    A subclass of :class:`InvalidEvent` so the event ``save()`` path treats it
    like any other validation failure, but distinct so the UI can render a
    dedicated "submission in progress" page. It may be raised from an event's
    ``validate_under_lock`` (with an ``event``) or from a controller pre-check
    (with just a ``message``).
    """

    def __init__(self, event: Event | None = None, message: str = '',
                 conflicting_submission_id: str | None = None) -> None:
        self.conflicting_submission_id = conflicting_submission_id
        if event is not None:
            super().__init__(event, message)
        else:
            self.event = None
            self.message = message
            self.report = None
            ValueError.__init__(self, message)


class NoSuchSubmission(RuntimeError):
    """An operation was performed on/for a submission that does not exist."""


class NoSuchDocument(RuntimeError):
    """An operation referenced an arXiv paper (document) that does not exist."""


class SaveError(RuntimeError):
    """Failed to persist event state."""


class NothingToDo(RuntimeError):
    """There is nothing to do."""
