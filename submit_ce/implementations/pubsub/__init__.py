"""submit-ce API implementation that sends pubsub events."""

from datetime import datetime
from typing import Optional, Tuple, List
import logging

from google.cloud import pubsub_v1

from submit_ce.api import SubmitApi, SubmissionFileStore
from submit_ce.domain import Event, Submission
from submit_ce.api.compile_service import CompileService
from submit_ce.domain.agent import Client, User
from submit_ce.domain.event.base import EventList
from submit_ce.domain.meta import License
from submit_ce.domain.types import SubmitFile
from submit_ce.domain.uploads import Workspace


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

    def save(self, *event, submission_id: Optional[str] = None) -> Tuple[Submission, List[Event]]:
        answer = self.inner_api.save(*event, submission_id=submission_id)
        pubsub_msg_id = self.publisher.publish(self.topic, self.serialize_msg(event)).result()
        logger.debug(f"submission_id: {submission_id} pubsub_msg_id: {pubsub_msg_id}")
        return answer

    def get(self, submission_id: str) -> Submission:
        return self.inner_api.get(submission_id)

    def get_with_history(self, submission_id: str) -> Tuple[Submission, List[Event]]:
        return self.inner_api.get_with_history(submission_id)

    def load_submissions_for_user(self, user_id: int) -> List[Submission]:
        return self.inner_api.load_submissions_for_user(user_id)

    def get_file_store(self) -> SubmissionFileStore:
        return self.inner_api.get_file_store()

    def get_compiler(self) -> CompileService:
        return self.inner_api.get_compiler()

    def categories_for_user(self, user_id: str) -> list[str]:
        return self.inner_api.categories_for_user(user_id)

    def licenses(self, active_only=True) -> List[License]:
        return self.inner_api.licenses(active_only)

    def next_announcement_time(self, reference: Optional[datetime] = None) -> datetime:
        return self.inner_api.next_announcement_time(reference)

    def next_freeze_time(self, reference: Optional[datetime] = None) -> datetime:
        return self.inner_api.next_freeze_time(reference)

    def healthy(self) -> tuple[bool,str]:
        return self.inner_api.healthy()

    def upload(self, files: SubmitFile, submission_id: str, user: User, client: Client) -> Workspace:
        return self.inner_api.upload(files, submission_id, user, client)

    @staticmethod
    def serialize_msg(*events: Event) -> bytes:
        """Serialize events to `bytes` to send as pubsub message."""
            
        # Extract only the Event objects from the incoming tuples.
        events_to_serialize = EventList([item[0] for item in events])
        return events_to_serialize.model_dump_json(by_alias=True).encode('utf-8')
