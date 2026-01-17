"""
Controller for verify_user action.

Creates an event of type `core.events.event.ConfirmContactInformation`
"""
from http import HTTPStatus as status
from typing import Tuple, Dict, Any, Optional

from flask import url_for, current_app
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError, NotFound, BadRequest
from wtforms import BooleanField
from wtforms.validators import InputRequired
import logging

from arxiv.forms import csrf
from arxiv.auth.domain import Session
from submit_ce.api.exceptions import SaveError

from submit_ce.ui.auth import user_and_client_from_session
from submit_ce.api.domain.event import ConfirmContactInformation

from submit_ce.ui.backend import get_submission
from submit_ce.ui.controllers.util import validate_command
from submit_ce.ui.routes.flow_control import ready_for_next, stay_on_this_stage
    
logger = logging.getLogger(__name__)    # pylint: disable=C0103

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]   # pylint: disable=C0103


def verify(method: str, params: MultiDict, session: Session,
           submission_id: int, **kwargs) -> Response:
    """
    Prompt the user to verify their contact information.

    Generates a `ConfirmContactInformation` event when valid data are POSTed.
    """
    logger.debug(f'method: {method}, submission: {submission_id}. {params}')
    submitter, client = user_and_client_from_session(session)

    # Will raise NotFound if there is no such submission.
    submission, _ = get_submission(submission_id)

    if method == 'GET' and submission.submitter_contact_verified:
        params['verify_user'] = 'true'

    form = VerifyUserForm(params)
    response_data = {
        'submission_id': submission_id,
        'form': form,
        'submission': submission,
        'submitter': submitter,
        'user': session.user,   # We want the most up-to-date representation.
    }

    if method == "GET":
        return stay_on_this_stage((response_data, status.OK, {}))
    if method != "POST":
        return response_data, status.METHOD_NOT_ALLOWED, {}

    if not form.validate() or not form.verify_user.data:
        return stay_on_this_stage((response_data, status.BAD_REQUEST, {}))
    
    if submission.submitter_contact_verified:
        return ready_for_next((response_data, status.OK,{}))

    cmd = ConfirmContactInformation(creator=submitter, client=client)
    if validate_command(form, cmd, submission, 'verify_user'):
        submission, _ = current_app.api.save(cmd, submission_id=submission_id)
        response_data['submission'] = submission
        return ready_for_next((response_data, status.OK, {}))
    else:
        return stay_on_this_stage((response_data, status.BAD_REQUEST, {}))


class VerifyUserForm(csrf.CSRFForm):
    """Generates form with single checkbox to confirm user information."""

    verify_user = BooleanField(
        'I confirm that my contact information is correct',
        [InputRequired('Please confirm your user information')],
    )
