import io
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple, List, IO

from submit_ce.api import SubmitApi, Event, Submission, License, SubmitFile, Agent, Client, Upload, SubmissionFileStore
from submit_ce.implementations.schedule import next_announcement_time, next_freeze_time

class NullFileStore(SubmissionFileStore):

    def get_workspace(self, submission_id: str) -> Optional[Upload]:
        return None

    def get_source_file(self, submission_id: str, path: Path) -> BytesIO:
        raise RuntimeError("No source file")

    def store_source_package(self, submission_id: str, content: SubmitFile, chunk_size) -> str:
        "Not stored, this is from a NullFileStore"

    def get_source_pacakge_checksum(self, submission_id: str) -> str:
        ""

    def does_source_exist(self, submission_id: str) -> bool:
        False

    def store_preview(self, submission_id: str, content: IO[bytes]) -> str:
        return "not really stored, NullFileStore"

    def get_preview(self, submission_id: str, path: Path) -> BytesIO:
        raise RuntimeError("No preview")

    def get_preview_checksum(self, submission_id: str) -> str:
        ""

    def does_preview_exist(self, submission_id: str) -> bool:
        False

    def is_available(self) -> bool:
        False


class NullImplementation(SubmitApi):
    """Submission that does as little as possible."""

    def get(self, submission_id: str) -> Submission:
        Submission(submission_id)

    def get_file_store(self, workspace_id) -> SubmissionFileStore:
        return NullFileStore()

    def upload(self, files: SubmitFile, submission_id: int, user: Agent, client: Client) -> Upload:
        return Upload()

    def licenses(self, active_only=True) -> List[License]:
        return []

    def categories_for_user(self, user_id: str) -> Optional[str]:
        return []

    def next_announcement_time(self, reference: Optional[datetime] = None) -> datetime:
        return next_announcement_time(reference)

    def next_freeze_time(self, reference: Optional[datetime] = None) -> datetime:
        return next_freeze_time(reference)

    def get_with_history(self, submission_id: int) -> Tuple[Submission, List[Event]]:
        return Submission(submission_id), []

    def load_submissions_for_user(self, user_id: int) -> List[Submission]:
        return []

    def save(self, *events: Event, submission_id: Optional[int] = None) -> Tuple[Submission, List[Event]]:
        submission = self.get_with_history(submission_id)
        for event in events:
            submission = event.apply(submission)

        return submission, events