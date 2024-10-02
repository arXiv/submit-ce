"""Request controllers for the submission UI."""
from http import HTTPStatus as status

from arxiv.auth.domain import Session
from werkzeug.datastructures import MultiDict

from submit_ce.ui.routes.flow_control import advance_to_current
from submit_ce.ui.util import load_submission
from . import util, jref, withdraw, delete, cross
from .new import process
from .new import upload
from .new.authorship import authorship
from .new.classification import classification, cross_list
from .new.create import create
from .new.final import finalize
from .new.license import license
from .new.metadata import metadata
from .new.metadata import optional
from .new.policy import policy
from .new.unsubmit import unsubmit
from .new.verify_user import verify
from .util import Response


# def submission_status(method: str, params: MultiDict, session: Session,
#                       submission_id: int) -> Response:
#     user, client = util.user_and_client_from_session(session)

#     # Will raise NotFound if there is no such submission.
#     submission, submission_events = load_submission(submission_id)
#     response_data = {
#         'submission': submission,
#         'submission_id': submission_id,
#         'events': submission_events
#     }
#     return response_data, status.OK, {}


def submission_edit(method: str, params: MultiDict, session: Session,
                    submission_id: int) -> Response:
    """Cause flow_control to go to the current_stage of the Submission."""
    submission, submission_events = load_submission(submission_id)
    response_data = {
        'submission': submission,
        'submission_id': submission_id,
        'events': submission_events,
    }
    return advance_to_current((response_data, status.OK, {}))