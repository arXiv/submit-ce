from typing import Optional, Tuple, List

from submit_ce.api import SubmitApi, Event, Submission


class NullImplementation(SubmitApi):
    """Submission that does almost as little as possible."""
    def load(self, submission_id: int) -> Tuple[Submission, List[Event]]:
        return Submission(submission_id), []

    def load_submissions_for_user(self, user_id: int) -> List[Submission]:
        return []

    def save(self, *events: Event, submission_id: Optional[int] = None) -> Tuple[Submission, List[Event]]:
        submission = self.load(submission_id)
        for event in events:
            submission = event.apply(submission)

        return submission, events