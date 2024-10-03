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
from werkzeug.datastructures import MultiDict
from wtforms.fields import RadioField
from wtforms.validators import InputRequired

from submit_ce.api.domain.events import SetLicense
from submit_ce.ui.backend import api, impl_data, get_user, get_client
from submit_ce.ui.routes.flow_control import ready_for_next, stay_on_this_stage
from submit_ce.ui.util import load_submission

logger = logging.getLogger(__name__)  # pylint: disable=C0103

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103


def license(method: str, params: MultiDict, session: Session,
            submission_id: int, **kwargs) -> Response:
    """Convert license form data into a `SetLicense` event."""
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
        if not license_uri:
            raise NotImplementedError("Currently we don't support removing a license from a submission")
        if submission.license and submission.license.uri == license_uri:
            return ready_for_next((response_data, status.OK, {}))
        else:
            # command = SetLicense(creator=submitter, client=client,
            #                      license_uri=license_uri)
            # if validate_command(form, command, submission, 'license'):
            #     try:
            #         submission, _ = save(command, submission_id=submission_id)
            #         return ready_for_next((response_data, status.OK, {}))
            #     except SaveError as e:
            #         raise InternalServerError(response_data) from e
            api.set_license_post(impl_data(), get_user(), get_client(),
                                 submission_id,
                                 SetLicense(license_uri=form.license.data))

    return stay_on_this_stage((response_data, status.OK, {}))


class LicenseForm(csrf.CSRFForm):
    """Generate form to select license."""

    LICENSE_CHOICES = [(uri, data['label']) for uri, data in LICENSES.items()
                       if data['is_current']]

    license = RadioField(u'Select a license', choices=LICENSE_CHOICES,
                         validators=[InputRequired('Please select a license')])
