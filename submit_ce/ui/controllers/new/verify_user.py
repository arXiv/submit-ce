"""
Controller for verify_user action.

Creates an event of type `core.events.event.ConfirmContactInformation`
"""
from http import HTTPStatus as status
from typing import Tuple, Dict, Any

from arxiv.auth.domain import Session
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError
from wtforms import BooleanField
from wtforms.validators import InputRequired

from arxiv.base import logging
from arxiv.forms import csrf

from submit_ce.api.domain.events import AuthorshipDirect
from submit_ce.ui.backend import save, api, get_client, get_user, impl_data
from submit_ce.ui.domain.event import ConfirmContactInformation
from submit_ce.ui.exceptions import SaveError

from submit_ce.ui.util import load_submission
from submit_ce.ui.controllers.util import validate_command, \
    user_and_client_from_session
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
    submission, _ = load_submission(submission_id)

    # Initialize the form with the current state of the submission.
    if method == 'GET':
        if submission.submitter_contact_verified:
            params['verify_user'] = 'true'

    form = VerifyUserForm(params)
    response_data = {
        'submission_id': submission_id,
        'form': form,
        'submission': submission,
        'submitter': submitter,
        'user': session.user,   # We want the most up-to-date representation.
    }

    if method == 'POST' and form.validate() and form.verify_user.data:
        # Now that we have a submission, we can verify the user's contact
        # information. There is no need to do this more than once.
        if submission.submitter_contact_verified:
            return ready_for_next((response_data, status.OK))
        else:
            api.assert_authorship_post(impl_data(), get_user(), get_client(),
                                       submission_id,
                                       AuthorshipDirect(i_am_author=form.verify_user.data))
            return ready_for_next((response_data, status.OK, {}))

    return stay_on_this_stage((response_data, status.OK, {}))


class VerifyUserForm(csrf.CSRFForm):
    """Generates form with single checkbox to confirm user information."""

    verify_user = BooleanField(
        'By checking this box, I verify that my user information is correct.',
        [InputRequired('Please confirm your user information')],
    )
