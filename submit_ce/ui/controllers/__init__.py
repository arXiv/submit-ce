"""Request controllers for the submission UI."""

#ruff: noqa: F401

from http import HTTPStatus as status
from typing import Optional

from arxiv.auth.domain import Session
from flask import current_app
from werkzeug.datastructures import MultiDict

from submit_ce.ui.routes.flow_control import advance_to_current

from ..backend import get_submission
from . import cross, delete, jref, util, withdraw
from .manage_submissions import manage_submissions
from .sword_license import sword_license
from .new import process, upload, review, preview
from .new.classification import classification
from .new.create import create
from .new.final import finalize
from .new.license import license
from .new.metadata import metadata
from .new.policy import policy
from .new.unsubmit import unsubmit
from .new.verify_user import verify
from .util import Response

_GS_CONSOLE = "https://console.cloud.google.com/storage/browser/"


def _gs_links(submission_id: str) -> tuple[Optional[str], Optional[str]]:
    """Return ``(gs_path, console_url)`` for the submission dir.

    ``gs_path`` is the ``gs://{bucket}/{path}`` URI (used as the link text)
    and ``console_url`` is the matching GCS console browser URL (the href).
    Both are None unless the file store reports a gs:// path (i.e. the GS
    store); local/null stores return "" and get ``(None, None)``.
    """
    try:
        path = current_app.api.get_file_store().get_full_submission_path(
            str(submission_id))
    except Exception:
        return None, None
    if path and path.startswith("gs://"):
        return path, _GS_CONSOLE + path[len("gs://"):]
    return None, None


def submission_status(method: str, params: MultiDict, session: Session,
                      submission_id: str) -> Response:
    #user, client = util.user_and_client_from_session(session)

    # Will raise NotFound if there is no such submission.
    submission, submission_events = get_submission(submission_id)
    gs_path, gs_console_url = _gs_links(submission_id)
    response_data = {
        'submission': submission,
        'submission_id': submission_id,
        'events': submission_events,
        'gs_path': gs_path,
        'gs_console_url': gs_console_url,
    }
    return response_data, status.OK, {}


def submission_edit(method: str, params: MultiDict, session: Session,
                    submission_id: str) -> Response:
    """Cause flow_control to go to the current_stage of the Submission."""
    submission, submission_events = get_submission(submission_id)
    gs_path, gs_console_url = _gs_links(submission_id)
    response_data = {
        'submission': submission,
        'submission_id': submission_id,
        'events': submission_events,
        'gs_path': gs_path,
        'gs_console_url': gs_console_url,
    }
    return advance_to_current((response_data, status.OK, {}))
