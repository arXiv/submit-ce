"""
Controller for policy action.

Creates an event of type `core.events.event.ConfirmPolicy`

TODO !!! add get_polices to api, read polices from api
"""

from http import HTTPStatus as status
from typing import Tuple, Dict, Any

from arxiv.auth.domain import Session
from arxiv.forms import csrf
from wtforms.fields.simple import HiddenField

from flask import current_app, request
from submit_ce.ui.auth import user_and_client_from_session
from werkzeug.datastructures import MultiDict
from wtforms import Field, ValidationError, widgets
from wtforms.validators import InputRequired

from submit_ce.domain.event import ConfirmPolicy
from submit_ce.ui.controllers.util import validate_command
from submit_ce.ui.routes.flow_control import ready_for_next, stay_on_this_stage
from submit_ce.ui.backend import get_submission


Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103


def policy(method: str, params: MultiDict, session: Session,
           submission_id: int, **kwargs) -> Response:
    """Convert policy form data into an `ConfirmPolicy` event."""
    submitter, client = user_and_client_from_session(session)
    submission, submission_events = get_submission(submission_id)

    if method == 'GET' and submission.submitter_accepts_policy:
        params['policy'] = 'y'

    current_policy_id=3  # TODO !!! add to api and use that
    form = PolicyForm(params, current_policy_id)
    response_data = {
        'submission_id': submission_id,
        'form': form,
        'submission': submission
    }

    if method == "GET":
        return stay_on_this_stage((response_data, status.OK, {}))
    if method != "POST":
        return response_data, status.METHOD_NOT_ALLOWED, {}

    valid_form = form.validate()
    if not valid_form:
        return stay_on_this_stage((response_data, status.BAD_REQUEST, {}))

    if not _only_allowed_fields(request.form):  # wtf form swallows unexpected fields
        form.policy.errors.append("Unexpected fields sent with request.")
        return stay_on_this_stage((response_data, status.BAD_REQUEST, {}))

    accept_policy = form.policy.data
    if accept_policy and submission.submitter_accepts_policy:
        return ready_for_next((response_data, status.OK, {}))

    if not accept_policy and submission.submitter_accepts_policy:
        form.policy.errors.append("Cannot unaccept policy once accepted")
        return stay_on_this_stage((response_data, status.BAD_REQUEST, {}))

    if not accept_policy and not submission.submitter_accepts_policy:
        form.policy.errors.append("To continue, please agree to the policy")
        return stay_on_this_stage((response_data, status.BAD_REQUEST, {}))

    if accept_policy and not submission.submitter_accepts_policy:
        command = ConfirmPolicy(creator=submitter, client=client,
                                agreement_id=form.policy_id.data)
        if validate_command(form, command, submission, 'policy'):
            submission.agreement_id = form.policy_id.data
            submission, _ = current_app.api.save(command, submission_id=submission_id)
            response_data['submission'] = submission
            return ready_for_next((response_data, status.OK, {}))
        else:
            return stay_on_this_stage((response_data, status.BAD_REQUEST, {}))


class PolicyCheckBoxField(Field):
    widget = widgets.CheckboxInput()

    def process_data(self, value):
        self.data = bool(value)

    def process_formdata(self, valuelist):
        """Only accept "y" as `True`."""
        if not valuelist or valuelist[0] != "y":
            self.data = False
        else:
            self.data = True

    def _value(self):
        if self.raw_data:
            return str(self.raw_data[0])
        return "y"


class PolicyForm(csrf.CSRFForm):
    """Generate form with checkbox to confirm policy."""
    current_policy_id=-1
    policy_id = HiddenField('PolicyId', validators=[InputRequired()])
    policy = PolicyCheckBoxField(
        'By checking this box, I agree to the policies listed on this page.',
        [InputRequired('Please check the box to agree to the policies')])

    def __init__(self, params, current_policy_id):
        super().__init__(params)
        self.current_policy_id = current_policy_id
        self.policy_id.data = current_policy_id

    def validate_policy_id(self, field):
        form_processed_data_matches_current_policy_id = field.data == self.current_policy_id
        raw_data_matches_current_policy_id = len(field.raw_data)==1 \
            and str(field.raw_data[0]) == str(self.current_policy_id)
        if field.data is None \
           or not form_processed_data_matches_current_policy_id \
           or not raw_data_matches_current_policy_id:
            raise ValidationError("Must use the current policy id")


ALLOWED_FIELDS = set(["policy_id","policy","csrf_token","action"])


def _only_allowed_fields(form:PolicyForm):
    fields_on_sent_form = set([field for field in form])
    return fields_on_sent_form.issubset(ALLOWED_FIELDS)
