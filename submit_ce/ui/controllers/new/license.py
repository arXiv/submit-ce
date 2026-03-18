"""
Controller for license action.

Creates an event of type `core.events.event.SetLicense`
"""

from http import HTTPStatus as status
from typing import Tuple, Dict, Any

from arxiv.auth.domain import Session
from arxiv.base import logging
from arxiv.forms import csrf
from arxiv.license import LICENSES

from flask import current_app
from submit_ce.ui.auth import user_and_client_from_session
from werkzeug.datastructures import MultiDict
from wtforms.fields import RadioField
from wtforms.validators import InputRequired

from submit_ce.domain.event import SetLicense
from submit_ce.ui.controllers.util import validate_command
from submit_ce.ui.routes.flow_control import ready_for_next, stay_on_this_stage
from submit_ce.ui.backend import get_submission


logger = logging.getLogger(__name__)  # pylint: disable=C0103

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103


def license(method: str, params: MultiDict, session: Session,
            submission_id: int, **kwargs) -> Response:
    """Convert license form data into a `SetLicense` event."""
    submitter, client = user_and_client_from_session(session)

    submission, _ = get_submission(submission_id)

    if method == 'GET' and submission.license:
        # prepopulated form based on current state of submission
        params['license'] = submission.license.uri

    form = LicenseForm(params)
    response_data = {
        'submission_id': submission_id,
        'form': form,
        'submission': submission
    }
    if method == "GET":
        return stay_on_this_stage((response_data, status.OK, {}))
    if method != "POST":
        return response_data, status.METHOD_NOT_ALLOWED, {}

    license_uri = form.license.data
    if submission.license and submission.license.uri == license_uri:
        return ready_for_next((response_data, status.OK, {}))

    command = SetLicense(creator=submitter, client=client, license_uri=license_uri)
    if validate_command(form, command, submission, 'license'):
        submission, _ = current_app.api.save(command, submission_id=submission_id)
        return ready_for_next((response_data, status.OK, {}))
    else:
        return stay_on_this_stage((response_data, status.BAD_REQUEST, {}))

class LicenseForm(csrf.CSRFForm):
    """Generate form to select license."""

    LICENSE_CHOICES = [(uri, data['label']) for uri, data in LICENSES.items()
                       if data['is_current']]

    license = RadioField(u'Select a license', choices=LICENSE_CHOICES,
                         validators=[InputRequired('Please select a license')])
