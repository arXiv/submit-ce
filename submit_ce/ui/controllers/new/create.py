"""Controller for creating a new ui-app."""

from http import HTTPStatus as status

from arxiv.auth.domain import Session
from arxiv.base import logging
from arxiv.forms import csrf
from flask import url_for
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError, BadRequest

from submit_ce.api.domain.event import CreateSubmission, \
    CreateSubmissionVersion
from submit_ce.api.exceptions import SaveError
from submit_ce.ui.backend import api
from submit_ce.ui.controllers.util import validate_command
from submit_ce.ui.routes.flow_control import advance_to_current, Response
from submit_ce.ui.backend import get_submission
from submit_ce.ui.auth import user_and_client_from_session

logger = logging.getLogger(__name__)    # pylint: disable=C0103


class CreateSubmissionForm(csrf.CSRFForm):
    """Submission creation form."""


def create(method: str, params: MultiDict, session: Session, *args,
           **kwargs) -> Response:
    """Create a new ui-app, and redirect to workflow."""
    submitter, client = user_and_client_from_session(session)
    response_data = {}
    if method == 'GET':     # Display a splash page.
        response_data['user_submissions'] = api.load_submissions_for_user(session.user.user_id)
        params = MultiDict()

    # We're using a form here for CSRF protection.
    form = CreateSubmissionForm(params)
    response_data['form'] = form

    command = CreateSubmission(creator=submitter, client=client)
    if method == 'POST' and form.validate() and validate_command(form, command):
        try:
            submission, _ = api.save(command)
        except SaveError as e:
            logger.error('Could not save command: %s', e)
            raise InternalServerError(response_data) from e

        # TODO Do we need a better way to enter a workflow?
        # Maybe a controller that is defined as the entrypoint?
        loc = url_for('ui.verify_user', submission_id=submission.submission_id)
        return {}, status.SEE_OTHER, {'Location': loc}

    return advance_to_current((response_data, status.OK, {}))


def replace(method: str, params: MultiDict, session: Session,
            submission_id: int, **kwargs) -> Response:
    """Create a new version, and redirect to workflow."""
    submitter, client = user_and_client_from_session(session)
    submission, submission_events = get_submission(submission_id)
    response_data = {
        'submission_id': submission_id,
        'ui-app': submission,
        'submitter': submitter,
        'client': client,
    }

    if method == 'GET':     # Display a splash page.
        response_data['form'] = CreateSubmissionForm()

    if method == 'POST':
        # We're using a form here for CSRF protection.
        form = CreateSubmissionForm(params)
        response_data['form'] = form
        if not form.validate():
            raise BadRequest('Invalid request')

        submitter, client = user_and_client_from_session(session)
        submission, _ = get_submission(submission_id)
        command = CreateSubmissionVersion(creator=submitter, client=client)
        if not validate_command(form, command, submission):
            raise BadRequest({})

        try:
            submission, _ = api.save(command, submission_id=submission_id)
        except SaveError as e:
            logger.error('Could not save command: %s', e)
            raise InternalServerError({}) from e

        loc = url_for('ui.verify_user', submission_id=submission.submission_id)
        return {}, status.SEE_OTHER, {'Location': loc}
    return response_data, status.OK, {}

