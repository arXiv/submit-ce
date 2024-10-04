from typing import Optional, Tuple, List

from submit_ce.api.core import CoreSubmitApi
from submit_ce.api.domain import Event, Submission


class FakeSubmitApi(CoreSubmitApi):
    """Implementation that just returns errors all the time."""
    def load(self, submission_id: int) -> Tuple[Submission, List[Event]]:
        return

    def load_submissions_for_user(self, user_id: int) -> List[Submission]:
        pass

    def load_fast(self, submission_id: int) -> Submission:
        pass

    def save(self, *events: Event, submission_id: Optional[int] = None) -> Tuple[Submission, List[Event]]:
        pass