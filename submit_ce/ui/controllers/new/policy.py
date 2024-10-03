"""
Controller for policy action.

Creates an event of type `core.events.event.ConfirmPolicy`
"""
from http import HTTPStatus as status
from typing import Tuple, Dict, Any

from arxiv.auth.domain import Session
from arxiv.forms import csrf
from werkzeug.datastructures import MultiDict
from wtforms import BooleanField
from wtforms.fields.simple import HiddenField
from wtforms.validators import InputRequired

from submit_ce.api.domain.events import AgreedToPolicy
from submit_ce.ui.backend import api, get_client, get_user, impl_data
from submit_ce.ui.controllers.util import user_and_client_from_session
from submit_ce.ui.routes.flow_control import ready_for_next, stay_on_this_stage
from submit_ce.ui.util import load_submission

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103


def policy(method: str, params: MultiDict, session: Session,
           submission_id: int, **kwargs) -> Response:
    """Handle policy form data."""
    submitter, client = user_and_client_from_session(session)
    submission, submission_events = load_submission(submission_id)

    if method == 'GET' and submission.submitter_accepts_policy:
        params['policy'] = 'true'

    form = PolicyForm(params)
    response_data = {
        'submission_id': submission_id,
        'form': form,
        'submission': submission
    }

    if method == 'POST' and form.validate():
        accept_policy = form.policy.data
        if accept_policy and submission.submitter_accepts_policy:
            return ready_for_next((response_data, status.OK, {}))
        if accept_policy and not submission.submitter_accepts_policy:
            # command = ConfirmPolicy(creator=submitter, client=client)
            # if validate_command(form, command, submission, 'policy'):
            #     try:
            #         submission, _ = save(command, submission_id=submission_id)
            #         response_data['submission'] = submission
            #         return ready_for_next((response_data, status.OK, {}))
            #     except SaveError as e:
            #         raise InternalServerError(response_data) from e
            api.accept_policy_post(impl_data(), get_user(), get_client(),
                                   submission_id,
                                   AgreedToPolicy(accepted_policy_id=int(form.policy_id.data)))
            return ready_for_next((response_data, status.OK, {}))

    return stay_on_this_stage((response_data, status.OK, {}))


class PolicyForm(csrf.CSRFForm):
    """Generate form with checkbox to confirm policy."""

    policy = BooleanField(
        'By checking this box, I agree to the policies listed on this page.',
        [InputRequired('Please check the box to agree to the policies')],
    )
    policy_id = HiddenField(
        'identifier for the policy on this page',
     )
