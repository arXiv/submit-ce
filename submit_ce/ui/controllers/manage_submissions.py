"""Controller for 'Manage Submissions' page."""

from http import HTTPStatus as status
import logging

from arxiv.auth.domain import Session
from arxiv.forms import csrf
from flask import url_for, current_app
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError, BadRequest

from submit_ce.api.domain.event import CreateSubmission, \
    CreateSubmissionVersion
from submit_ce.api.exceptions import SaveError

from submit_ce.ui.auth import user_and_client_from_session
from submit_ce.ui.controllers.util import validate_command
from submit_ce.ui.routes.flow_control import advance_to_current, Response
from submit_ce.ui.backend import get_submission

logger = logging.getLogger(__name__)    # pylint: disable=C0103


class CreateSubmissionForm(csrf.CSRFForm):
    """Submission creation form."""


def manage_submissions(method: str, params: MultiDict, session: Session, *args,
           **kwargs) -> Response:
    """Create a new submission, and redirect to workflow."""
    submitter, client = user_and_client_from_session(session)
    response_data = {}
    if method == 'GET':     # Display a splash page.
        response_data['user_submissions'] = current_app.api.load_submissions_for_user(session.user.user_id)
        params = MultiDict()

    # We're using a form here for CSRF protection.
    form = CreateSubmissionForm(params)
    response_data['form'] = form

    command = CreateSubmission(creator=submitter, client=client)
    if method == 'POST' and form.validate() and validate_command(form, command):
        try:
            submission, _ = current_app.api.save(command)
        except SaveError as e:
            logger.error('Could not save command: %s', e)
            raise InternalServerError(response_data) from e

        # TODO Do we need a better way to enter a workflow?
        # Maybe a controller that is defined as the entrypoint?
        loc = url_for('ui.verify_user', submission_id=submission.submission_id)
        return {}, status.SEE_OTHER, {'Location': loc}

    return advance_to_current((response_data, status.OK, {}))
