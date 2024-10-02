"""Provide the controller used to unsubmit/unfinalize a submission."""

from http import HTTPStatus as status

from arxiv.auth.domain import Session
from flask import url_for
from wtforms import BooleanField, validators
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import BadRequest, InternalServerError

from arxiv.base import alerts
from arxiv.forms import csrf
from submit_ce.ui.backend import save
from submit_ce.ui.domain.event import UnFinalizeSubmission

from submit_ce.ui.controllers.util import Response, user_and_client_from_session, validate_command
from submit_ce.ui.util import load_submission

class UnsubmitForm(csrf.CSRFForm):
    """Form for unsubmitting a submission."""

    confirmed = BooleanField('Confirmed',
                             validators=[validators.DataRequired()])


def unsubmit(method: str, params: MultiDict, session: Session,
             submission_id: int, **kwargs) -> Response:
    """Unsubmit a submission."""
    submission, submission_events = load_submission(submission_id)
    response_data = {
        'submission': submission,
        'submission_id': submission.submission_id,
    }

    if method == 'GET':
        form = UnsubmitForm()
        response_data.update({'form': form})
        return response_data, status.OK, {}
    elif method == 'POST':
        form = UnsubmitForm(params)
        response_data.update({'form': form})
        if form.validate() and form.confirmed.data:
            user, client = user_and_client_from_session(session)
            command = UnFinalizeSubmission(creator=user, client=client)
            if not validate_command(form, command, submission, 'confirmed'):
                raise BadRequest(response_data)

            try:
                save(command, submission_id=submission_id)
            except Exception as e:
                alerts.flash_failure("Whoops!")
                raise InternalServerError(response_data) from e
            alerts.flash_success("Unsubmitted.")
            redirect = url_for('ui.create_submission')
            return {}, status.SEE_OTHER, {'Location': redirect}
        response_data.update({'form': form})
        # TODO not updated to non-BadRequest convention
        raise BadRequest(response_data)
