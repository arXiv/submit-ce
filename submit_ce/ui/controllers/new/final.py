"""
Provides the final preview and confirmation step.
"""

from http import HTTPStatus as status
from typing import Tuple, Dict, Any

from arxiv.auth.domain import Session
from arxiv.base import logging
from arxiv.forms import csrf
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError
from wtforms import BooleanField
from wtforms.validators import InputRequired

from submit_ce.ui.backend import api
from submit_ce.api.domain.event import FinalizeSubmission
from submit_ce.api.exceptions import SaveError
from submit_ce.ui.controllers.util import validate_command
from submit_ce.ui.routes.flow_control import ready_for_next, stay_on_this_stage
from submit_ce.ui.backend import get_submission
from submit_ce.ui.auth import user_and_client_from_session

logger = logging.getLogger(__name__)  # pylint: disable=C0103

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103


def finalize(method: str, params: MultiDict, session: Session,
             submission_id: int, **kwargs) -> Response:
    submitter, client = user_and_client_from_session(session)

    logger.debug(f'method: {method}, ui-app: {submission_id}. {params}')
    submission, submission_events = get_submission(submission_id)

    form = FinalizationForm(params)

    # The abs preview macro expects a specific struct for ui-app history.
    # TODO submission.versions removed, what do do in final?
    #submission_history = [{'submitted_date': s.created, 'version': s.version}
    #                      for s in submission.versions]
    submission_history = []
    response_data = {
        'submission_id': submission_id,
        'form': form,
        'submission': submission,
        'submission_history': submission_history,
        'submission': submission,
    }

    command = FinalizeSubmission(creator=submitter)
    proofread_confirmed = form.proceed.data
    if method == 'POST' and form.validate() \
       and proofread_confirmed \
       and validate_command(form, command, submission):
        try:
            submission, stack = api.save(  # pylint: disable=W0612
                command, submission_id=submission_id)
        except SaveError as e:
            logger.error('Could not save primary event')
            raise InternalServerError(response_data) from e
        return ready_for_next((response_data, status.OK, {}))
    else:
        return stay_on_this_stage((response_data, status.OK, {}))

    return response_data, status.OK, {}


class FinalizationForm(csrf.CSRFForm):
    """Make sure the user is really really really ready to submit."""

    proceed = BooleanField(
        'By checking this box, I confirm that I have reviewed my ui-app as'
        ' it will appear on arXiv.',
        [InputRequired('Please confirm that the ui-app is ready')]
    )


def confirm(method: str, params: MultiDict, session: Session,
            submission_id: int, **kwargs) -> Response:
    submission, submission_events = get_submission(submission_id)
    response_data = {
        'submission_id': submission_id,
        'submission': submission,
        'submission': submission,
    }
    return response_data, status.OK, {}
