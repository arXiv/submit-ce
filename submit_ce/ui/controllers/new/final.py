"""
Provides the final preview and confirmation step.
"""

from typing import Tuple, Dict, Any

from arxiv.auth.domain import Session
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError
from wtforms import BooleanField
from wtforms.validators import InputRequired

from http import HTTPStatus as status
from arxiv.forms import csrf
from arxiv.base import logging
from submit_ce.ui.backend import save
from submit_ce.ui.domain.event import FinalizeSubmission
from submit_ce.ui.exceptions import SaveError
from submit_ce.ui.util import load_submission
from submit_ce.ui.controllers.util import validate_command, user_and_client_from_session
from submit_ce.ui.routes.flow_control import ready_for_next, stay_on_this_stage

logger = logging.getLogger(__name__)  # pylint: disable=C0103

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103


def finalize(method: str, params: MultiDict, session: Session,
             submission_id: int, **kwargs) -> Response:
    submitter, client = user_and_client_from_session(session)

    logger.debug(f'method: {method}, submission: {submission_id}. {params}')
    submission, submission_events = load_submission(submission_id)

    form = FinalizationForm(params)

    # The abs preview macro expects a specific struct for submission history.
    submission_history = [{'submitted_date': s.created, 'version': s.version}
                          for s in submission.versions]
    response_data = {
        'submission_id': submission_id,
        'form': form,
        'submission': submission,
        'submission_history': submission_history
    }

    command = FinalizeSubmission(creator=submitter)
    proofread_confirmed = form.proceed.data
    if method == 'POST' and form.validate() \
       and proofread_confirmed \
       and validate_command(form, command, submission):
        try:
            submission, stack = save(  # pylint: disable=W0612
                command, submission_id=submission_id)
        except SaveError as e:
            logger.error('Could not save primary event')
            raise InternalServerError(response_data) from e
        return ready_for_next((response_data, status.OK, {}))
    else:
        return stay_on_this_stage((response_data, status.OK, {}))

    return response_data, status.OK, {}


class FinalizationForm(csrf.CSRFForm):
    """Make sure the user is really really really ready to submit_ce."""

    proceed = BooleanField(
        'By checking this box, I confirm that I have reviewed my submission as'
        ' it will appear on arXiv.',
        [InputRequired('Please confirm that the submission is ready')]
    )


def confirm(method: str, params: MultiDict, session: Session,
            submission_id: int, **kwargs) -> Response:
    submission, submission_events = load_submission(submission_id)
    response_data = {
        'submission_id': submission_id,
        'submission': submission
    }
    return response_data, status.OK, {}
