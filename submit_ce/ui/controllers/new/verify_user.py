"""
Controller for verify_user action.

Creates an event of type `core.events.event.ConfirmContactInformation`
"""

from http import HTTPStatus as status
from typing import Tuple, Dict, Any

from flask import current_app
from werkzeug.datastructures import MultiDict
from wtforms import BooleanField, StringField
from wtforms.validators import InputRequired, Optional, Email, Length
import logging

from arxiv.auth.auth import scopes
from arxiv.forms import csrf
from arxiv.auth.domain import Session

from submit_ce.ui.auth import user_and_client_from_session
from submit_ce.domain.event import ConfirmContactInformation, SetProxyInformation

from submit_ce.ui.backend import get_submission
from submit_ce.ui.controllers.util import validate_command
from submit_ce.ui.routes.flow_control import ready_for_next, stay_on_this_stage

logger = logging.getLogger(__name__)  # pylint: disable=C0103

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103


def verify(method: str, params: MultiDict, session: Session,
           submission_id: str, **kwargs) -> Response:
    """
    Prompt the user to verify their contact information.

    Generates a `ConfirmContactInformation` event when valid data are POSTed.
    """
    logger.debug(f'method: {method}, submission: {submission_id}. {params}')
    submitter, client = user_and_client_from_session(session)

    # Will raise NotFound if there is no such submission.
    submission, _ = get_submission(submission_id)
    may_proxy = scopes.PROXY_SUBMISSION in submitter.scopes

    if method == 'GET' and submission.submitter_contact_verified:
        params['verify_user'] = 'true'

    if method == "GET":

        if submission.proxy:
            params['proxy_name'] = submission.creator.name
            params['proxy_email'] = submission.creator.email

    form = VerifyUserForm(params)
    response_data = {
        'submission_id': submission_id,
        'form': form,
        'submission': submission,
        'submitter': submitter,
        'user': session.user,  # We want the most up-to-date representation.
        'may_proxy': may_proxy,
    }

    if method == "GET":
        return stay_on_this_stage((response_data, status.OK, {}))
    if method != "POST":
        return response_data, status.METHOD_NOT_ALLOWED, {}

    if not form.validate() or not form.verify_user.data:
        return stay_on_this_stage((response_data, status.BAD_REQUEST, {}))

    if may_proxy:
        ok = True
        if not (form.proxy_name.data or "").strip():
            form.proxy_name.errors.append("Proxy for name is required.")
            ok = False
        if not (form.proxy_email.data or "").strip():
            form.proxy_email.errors.append("Proxy for e‑mail is required.")
            ok = False
        if not ok:
            return stay_on_this_stage((response_data, status.BAD_REQUEST, {}))

    # We need to process proxy changes
    #
    # if submission.submitter_contact_verified:
    #    return ready_for_next((response_data, status.OK,{}))

    if may_proxy and (form.proxy_name.data or form.proxy_email.data):

        proxied_name=form.proxy_name.data.strip()
        proxied_email=form.proxy_email.data.strip()

        if proxied_name != submission.contact_name or proxied_email != submission.contact_email:
            cmd = SetProxyInformation(
                creator=submitter,
                client=client,
                proxied_name=form.proxy_name.data.strip(),
                proxied_email=form.proxy_email.data.strip(),
                proxy_name=submitter.name,
            )
            submission, _ = current_app.api.save(cmd, submission_id=submission_id)

    # Edge Case: What do we do if proxy information has been saved but the submitter
    #            no longer has proxy permissions (revoked)? That is, a submitter's
    #            may_proxy permission is revoked while submission is in working state.
    #
    #            I've been told that proxy permissions are permanent.
    #
    #            In the event the permission to proxy is revoked, for submissions being
    #            worked on, the submitter_name and submitter_email will remain set to
    #            proxied values (they are not reset to actual submitter
    #
    #            I have removed the ClearProxyInformation event.

    cmd = ConfirmContactInformation(creator=submitter, client=client)

    if validate_command(form, cmd, submission, 'verify_user'):
        submission, _ = current_app.api.save(cmd, submission_id=submission_id)
        response_data['submission'] = submission
        return ready_for_next((response_data, status.OK, {}))
    else:
        return stay_on_this_stage((response_data, status.BAD_REQUEST, {}))


class VerifyUserForm(csrf.CSRFForm):
    """Generates form with single checkbox to confirm user information."""

    verify_user = BooleanField(
        'I confirm that my contact information is correct',
        [InputRequired('Please confirm your user information')],
    )

    proxy_name = StringField('Proxy for name',
                             validators=[Optional(), Length(max=200)])
    proxy_email = StringField('Proxy for e-mail',
                              validators=[Optional(), Email("Enter a valid e-mail address.")])
