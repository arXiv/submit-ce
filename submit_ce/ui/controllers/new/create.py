"""Controller for creating a new submission."""

from http import HTTPStatus as status

from arxiv.auth.domain import Session
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError, BadRequest
from flask import url_for
from retry import retry

from arxiv.forms import csrf
from arxiv.base import logging

from submit_ce.api.domain.events import StartedNew
from submit_ce.ui.backend import save, api, get_client, get_user, impl_data
from submit_ce.ui.domain.event import CreateSubmission, \
    CreateSubmissionVersion
from submit_ce.ui.exceptions import SaveError

from submit_ce.ui.controllers.util import Response, user_and_client_from_session, validate_command
from submit_ce.ui.util import load_submission
from submit_ce.ui.routes.flow_control import advance_to_current

logger = logging.getLogger(__name__)    # pylint: disable=C0103


class CreateSubmissionForm(csrf.CSRFForm):
    """Submission creation form."""


def create(method: str, params: MultiDict, session: Session, *args,
           **kwargs) -> Response:
    """Create a new submission, and redirect to workflow."""
    submitter, client = user_and_client_from_session(session)
    response_data = {}
    if method == 'GET':     # Display a splash page.
        response_data['user_submissions'] = api.user_submissions(impl_data(),get_user(),get_client())
        params = MultiDict()

    form = CreateSubmissionForm(params) # zero field form here for CSRF protection
    response_data['form'] = form

    command = CreateSubmission(creator=submitter, client=client)
    if method == 'POST' and form.validate() and validate_command(form, command):
        submisison_id = api.start(impl_data(), get_user(), get_client(), StartedNew() )
        # enter a workflow for the first time with a new sub id
        loc = url_for('ui.verify_user', submission_id=submisison_id)
        return {}, status.SEE_OTHER, {'Location': loc}
    else:
        return advance_to_current((response_data, status.OK, {}))


def replace(method: str, params: MultiDict, session: Session,
            submission_id: int, **kwargs) -> Response:
    """Create a new version, and redirect to workflow."""
    submitter, client = user_and_client_from_session(session)
    submission, submission_events = load_submission(submission_id)
    response_data = {
        'submission_id': submission_id,
        'submission': submission,
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
        submission, _ = load_submission(submission_id)
        command = CreateSubmissionVersion(creator=submitter, client=client)
        if not validate_command(form, command, submission):
            raise BadRequest({})

        try:
            submission, _ = save(command, submission_id=submission_id)
        except SaveError as e:
            logger.error('Could not save command: %s', e)
            raise InternalServerError({}) from e

        loc = url_for('ui.verify_user', submission_id=submission.submission_id)
        return {}, status.SEE_OTHER, {'Location': loc}
    return response_data, status.OK, {}
