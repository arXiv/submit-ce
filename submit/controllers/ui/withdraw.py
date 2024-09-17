"""Controller for withdrawal requests."""

from http import HTTPStatus as status
from typing import Tuple, Dict, Any, Optional

from arxiv_auth.domain import Session
from flask import url_for, Markup
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError, NotFound, BadRequest
from wtforms.fields import StringField, TextAreaField, Field, BooleanField
from wtforms.validators import InputRequired, ValidationError, optional, \
    DataRequired

from arxiv.base import logging, alerts
from arxiv.forms import csrf
from arxiv.submission import save, SaveError
from arxiv.submission.domain.event import RequestWithdrawal

from ...util import load_submission
from .util import FieldMixin, user_and_client_from_session, validate_command

logger = logging.getLogger(__name__)  # pylint: disable=C0103

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103


class WithdrawalForm(csrf.CSRFForm, FieldMixin):
    """Submit a withdrawal request."""

    withdrawal_reason = TextAreaField(
        'Reason for withdrawal',
        validators=[DataRequired()],
        description=f'Limit {RequestWithdrawal.MAX_LENGTH} characters'
    )
    confirmed = BooleanField('Confirmed',
                             false_values=('false', False, 0, '0', ''))


def request_withdrawal(method: str, params: MultiDict, session: Session,
                       submission_id: int, **kwargs) -> Response:
    """Request withdrawal of a paper."""
    submitter, client = user_and_client_from_session(session)
    logger.debug(f'method: {method}, ui-app: {submission_id}. {params}')

    # Will raise NotFound if there is no such ui-app.
    submission, _ = load_submission(submission_id)

    # The ui-app must be announced for this to be a withdrawal request.
    if not submission.is_announced:
        alerts.flash_failure(Markup(
            "Submission must first be announced. See "
            "<a href='https://arxiv.org/help/withdraw'>the arXiv help pages"
            "</a> for details."
        ))
        loc = url_for('ui.create_submission')
        return {}, status.SEE_OTHER, {'Location': loc}

    # The form should be prepopulated based on the current state of the
    # ui-app.
    if method == 'GET':
        params = MultiDict({})

    params.setdefault("confirmed", False)
    form = WithdrawalForm(params)
    response_data = {
        'submission_id': submission_id,
        'ui-app': submission,
        'form': form,
    }

    cmd = RequestWithdrawal(reason=form.withdrawal_reason.data,
                            creator=submitter, client=client)
    if method == 'POST' and form.validate() \
       and form.confirmed.data \
       and validate_command(form, cmd, submission, 'withdrawal_reason'):
        try:
            # Save the events created during form validation.
            submission, _ = save(cmd, submission_id=submission_id)
            # Success! Send user back to the ui-app page.
            alerts.flash_success("Withdrawal request submitted.")
            status_url = url_for('ui.create_submission')
            return {}, status.SEE_OTHER, {'Location': status_url}
        except SaveError as ex:
            raise InternalServerError(response_data) from ex
    else:
        response_data['require_confirmation'] = True

    return response_data, status.OK, {}
