"""Events that are intended to be backward compatable with legacy submit 1.5."""


from pydantic import Field
from submit_ce.domain.event.base import EventWithSideEffect
from submit_ce.domain.exceptions import InvalidEvent
from submit_ce.domain.submission import Submission


class Withdraw(EventWithSideEffect):
    """Make a submission for a older style paper withdraw aka `wdr`."""

    NAME = "withdraw"
    NAMED = "withdrawn"

    comments: str = Field(min_length=10, max_length=400)
    abstract: str = Field(min_length=10, max_length=1920)

    # TODO How is the wdr associated with the document or original submission?

    def validate(self, submission: Submission) -> None:
        """Make sure that a reason was provided."""
        if not submission.is_announced:
            raise InvalidEvent(self, "Submission must already be announced")

    def project(self, submission: Submission) -> Submission:
        """Update the submission status and withdrawal reason."""
        assert self.created is not None
        submission.is_source_processed = True
        submission.type = 'wdr'
        submission.source_format = 'withdrawn'
        return submission
