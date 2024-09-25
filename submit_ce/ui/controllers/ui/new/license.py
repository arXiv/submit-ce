"""
Controller for license action.

Creates an event of type `core.events.event.SetLicense`
"""

from http import HTTPStatus as status
from typing import Tuple, Dict, Any

from arxiv.auth.domain import Session
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError
from wtforms.fields import RadioField
from wtforms.validators import InputRequired

from arxiv.forms import csrf
from arxiv.base import logging
from arxiv.license import LICENSES
from submit_ce.ui.core import save
from submit_ce.ui.domain.event import SetLicense
from submit_ce.ui.exceptions import SaveError
from submit_ce.ui.util import load_submission
from submit_ce.ui.controllers.ui.util import validate_command, user_and_client_from_session
from submit_ce.ui.routes.ui.flow_control import ready_for_next, stay_on_this_stage


logger = logging.getLogger(__name__)  # pylint: disable=C0103

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103


def license(method: str, params: MultiDict, session: Session,
            submission_id: int, **kwargs) -> Response:
    """Convert license form data into a `SetLicense` event."""
    submitter, client = user_and_client_from_session(session)

    submission, submission_events = load_submission(submission_id)

    if method == 'GET' and submission.license:
        # The form should be prepopulated based on the current state of the
        # submission.
        params['license'] = submission.license.uri

    form = LicenseForm(params)
    response_data = {
        'submission_id': submission_id,
        'form': form,
        'submission': submission
    }

    if method == 'POST' and form.validate():
        license_uri = form.license.data
        if submission.license and submission.license.uri == license_uri:
            return ready_for_next((response_data, status.OK, {}))
        if not submission.license \
           or submission.license.uri != license_uri:
            command = SetLicense(creator=submitter, client=client,
                                 license_uri=license_uri)
            if validate_command(form, command, submission, 'license'):
                try:
                    submission, _ = save(command, submission_id=submission_id)
                    return ready_for_next((response_data, status.OK, {}))
                except SaveError as e:
                    raise InternalServerError(response_data) from e

    return stay_on_this_stage((response_data, status.OK, {}))


class LicenseForm(csrf.CSRFForm):
    """Generate form to select license."""

    LICENSE_CHOICES = [(uri, data['label']) for uri, data in LICENSES.items()
                       if data['is_current']]

    license = RadioField(u'Select a license', choices=LICENSE_CHOICES,
                         validators=[InputRequired('Please select a license')])
