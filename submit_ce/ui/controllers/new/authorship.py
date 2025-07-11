"""
Controller for authorship action.

Creates an event of type `core.events.event.ConfirmAuthorship`
"""

from http import HTTPStatus as status
from typing import Tuple, Dict, Any

from arxiv.auth.domain import Session

from arxiv.base import logging
from arxiv.forms import csrf

from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError
from wtforms import BooleanField, RadioField
from wtforms.validators import InputRequired, ValidationError, optional

from submit_ce.api.domain.event import ConfirmAuthorship
from submit_ce.api.exceptions import SaveError

from submit_ce.ui.backend import api
from submit_ce.ui.auth import user_and_client_from_session
from submit_ce.ui.controllers.util import validate_command
from submit_ce.ui.routes.flow_control import ready_for_next
from submit_ce.ui.backend import get_submission

# from arxiv-submission-core.events.event import ConfirmContactInformation

logger = logging.getLogger(__name__)  # pylint: disable=C0103

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103


def authorship(method: str, params: MultiDict, session: Session,
               submission_id: int, **kwargs) -> Response:
    """Handle the authorship assertion view."""
    submitter, client = user_and_client_from_session(session)
    submission, submission_events = get_submission(submission_id)

    # The form should be prepopulated based on the current state of the
    # submission.
    if method == 'GET':
        # Update form data based on the current state of the submission.
        if submission.submitter_is_author is not None:
            if submission.submitter_is_author:
                params['authorship'] = AuthorshipForm.YES
            else:
                params['authorship'] = AuthorshipForm.NO
            if submission.submitter_is_author is False:
                params['proxy'] = True

    form = AuthorshipForm(params)
    response_data = {
        'submission_id': submission_id,
        'form': form,
        'submission': submission,
        'submitter': submitter,
        'client': client,
    }

    if method == 'POST' and form.validate():
        value = (form.authorship.data == form.YES)
        # No need to do this more than once.
        if submission.submitter_is_author != value:
            command = ConfirmAuthorship(creator=submitter, client=client,
                                        submitter_is_author=value)
            if validate_command(form, command, submission, 'authorship'):
                try:
                    submission, _ = api.save(command, submission_id=submission_id)
                    response_data['submission'] = submission
                    return response_data, status.SEE_OTHER, {}
                except SaveError as e:
                    raise InternalServerError(response_data) from e
        return ready_for_next((response_data, status.OK, {}))
    
    return response_data, status.OK, {}


class AuthorshipForm(csrf.CSRFForm):
    """Generate form with radio button to confirm authorship information."""

    YES = 'y'
    NO = 'n'

    authorship = RadioField(choices=[(YES, 'I am an author of this paper'),
                                     (NO, 'I am not an author of this paper')],
                            validators=[InputRequired('Please choose one')])
    proxy = BooleanField('By checking this box, I certify that I have '
                         'received authorization from arXiv to submit papers '
                         'on behalf of the author(s).',
                         validators=[optional()])

    def validate_authorship(self, field: RadioField) -> None:
        """Require proxy field if submitter is not author."""
        if field.data == self.NO and not self.data.get('proxy'):
                raise ValidationError('You must get prior approval to submit '
                                      'on behalf of authors')
