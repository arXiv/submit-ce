"""submit-ce API implementation that sends pubsub events."""

from typing import Optional, Tuple, List
import logging

from google.cloud import pubsub_v1

from submit_ce.api import SubmitApi, SubmissionFileStore
from submit_ce.domain import Event, Submission
from submit_ce.api.CompileService import CompileService
from submit_ce.domain.event.base import EventList


logger = logging.getLogger(__name__)


class PubsubEventSubmitImplementation(SubmitApi):
    """Implementation of `SubmitApi` that sends a GCP pubsub message on `save()` of a change to a submission.

    This does not send pubsub events on any other calls."""
    def __init__(self,
                 publisher: pubsub_v1.PublisherClient,
                 topic: str,
                 inner_api: SubmitApi):
        self.publisher = publisher
        self.topic = topic
        self.inner_api = inner_api

    def save(self, *event, submission_id: Optional[int] = None) -> Tuple[Submission, List[Event]]:
        answer = self.inner_api.save(*event, submission_id=submission_id)
        pubsub_msg_id = self.publisher.publish(self.topic, self.serialize_msg(event)).result()
        logger.debug(f"submission_id: {submission_id} pubsub_msg_id: {pubsub_msg_id}")
        return answer

    def get(self, submission_id: str) -> Submission:
        return self.inner_api.get(submission_id)

    def get_with_history(self, submission_id: int) -> Tuple[Submission, List[Event]]:
        return self.inner_api.get_with_history(submission_id)

    def load_submissions_for_user(self, user_id: int) -> List[Submission]:
        return self.inner_api.load_submissions_for_user(user_id)

    def get_file_store(self) -> SubmissionFileStore:
        return self.inner_api.get_file_store()

    def get_compiler(self) -> CompileService:
        return self.inner_api.get_compiler()

    @staticmethod
    def serialize_msg(*events: Event) -> bytes:
        """Serialize events to `bytes` to send as pubsub message."""
            
        # Extract only the Event objects from the incoming tuples.
        events_to_serialize = EventList([item[0] for item in events])
        return events_to_serialize.model_dump_json(by_alias=True).encode('utf-8')
