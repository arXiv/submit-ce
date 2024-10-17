from typing import Optional, List

from ..config import Settings
from submit_ce.api.domain import Event, Submission, User, Client

def config_backend_api(settings: Settings)-> None:
    pass

def save(*events: Event, submission_id: Optional[str] = None) -> Submission:
    return None


def get_user() -> User:
    return None


def get_client() -> Client:
    return None


def impl_data() -> dict:
    return None


def api():
    return None


def get_submission() -> Optional[Submission]:
    return None


class SaveError(Exception):
    pass


def load_submissions_for_user(user_id: str) -> List[Submission]:
    return None