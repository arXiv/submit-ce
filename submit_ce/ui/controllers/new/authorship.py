"""
Controller for authorship action.

Creates an event of type `core.events.event.ConfirmAuthorship`
"""

from http import HTTPStatus as status
from typing import Tuple, Dict, Any

from arxiv.auth.auth import scopes
from arxiv.auth.domain import Session

from arxiv.forms import csrf

from flask import current_app
from werkzeug.datastructures import MultiDict
from wtforms import BooleanField, RadioField
from wtforms.validators import InputRequired, ValidationError, optional

from submit_ce.api.domain.event import ConfirmAuthorship

from submit_ce.ui.auth import user_and_client_from_session
from submit_ce.ui.controllers.util import validate_command
from submit_ce.ui.routes.flow_control import ready_for_next
from submit_ce.ui.backend import get_submission

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103


def authorship(method: str, params: MultiDict, session: Session,
               submission_id: int, **kwargs) -> Response:
    """Handle the authorship assertion view."""
    submitter, client = user_and_client_from_session(session)
    submission, _ = get_submission(submission_id)
    may_proxy = scopes.PROXY_SUBMISSION in submitter.scopes

    # The form should be prepopulated based on the current state of the submission.
    if method == 'GET':
        match submission.submitter_is_author, may_proxy:
            case True, False:  # already did form, is author
                params['authorship'] = AuthorshipForm.YES
            case True, True:  # already did form
                params['authorship'] = AuthorshipForm.YES
                params['proxy'] = False
            case False, True:  # already did form and set False while being a proxy
                params['authorship'] = AuthorshipForm.NO
                params['proxy'] = True
            case False, False:  # bad state: not proxy and marked not author
                params['authorship'] = False
            case _, _:
                pass # default values from form

    form = AuthorshipProxyForm(params) if may_proxy else  AuthorshipForm(params)

    response_data = {
        'submission_id': submission_id,
        'form': form,
        'submission': submission,
        'submitter': submitter,
        'client': client,
        'may_proxy': may_proxy,
    }

    if method == "GET":            
        return response_data, status.OK, {}
    if method != "POST":
        return response_data, status.METHOD_NOT_ALLOWED, {}
    if not form.validate():
        return response_data, status.BAD_REQUEST, {}        

    value = form.authorship.data == form.YES
    not_yet_done = submission.submitter_is_author != value
    command = ConfirmAuthorship(creator=submitter, client=client,
                                submitter_is_author=value)
    if not_yet_done and validate_command(form, command, submission, 'authorship'):
            submission, _ = current_app.api.save(command, submission_id=submission_id)
            response_data['submission'] = submission
    
    return ready_for_next((response_data, status.OK, {}))



class AuthorshipForm(csrf.CSRFForm):
    """Generate form with radio button to confirm authorship information."""

    YES = 'y'
    NO = 'n'

    authorship = RadioField(choices=[(YES, 'I am an author of this paper'),
                                     (NO, 'I am not an author of this paper')],
                            validators=[InputRequired('Please choose one')],
                            default=None)

    def validate_authorship(self, field: RadioField) -> None:
        """Require proxy field if submitter is not author."""
        if field.data == self.NO:
            # TODO could use better not author message
            raise ValidationError('You must be the author of the paper you want to submit.')


class AuthorshipProxyForm(csrf.CSRFForm):
    """Generate form with radio button to confirm authorship information."""

    YES = 'y'
    NO = 'n'

    authorship = RadioField(choices=[(YES, 'I am an author of this paper'),
                                     (NO, 'I am not an author of this paper')],
                            validators=[InputRequired('Please choose one')],
                            default=YES)
    proxy = BooleanField('By checking this box, I certify that I have '
                         'received authorization from arXiv to submit papers '
                         'on behalf of the author(s).',
                         validators=[optional()])

    def validate_authorship(self, field: RadioField) -> None:
        """Require proxy field if submitter is not author."""
        if field.data == self.NO and not self.data.get('proxy'):
                raise ValidationError('You must get prior approval to submit '
                                      'on behalf of authors')
