"""Controller for withdrawal requests."""

from http import HTTPStatus as status
from typing import Tuple, Dict, Any
import logging

from arxiv.auth.domain import Session
from flask import url_for, current_app
from markupsafe import Markup
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError, NotFound
from wtforms.fields import TextAreaField, BooleanField
from wtforms.validators import DataRequired, Length

from arxiv.base import alerts
from arxiv.forms import csrf
from submit_ce.domain.event import FinalizeSubmission
from submit_ce.domain.event.legacy import Withdraw

from .util import FieldMixin, validate_command
from submit_ce.ui.backend import get_submission
from ..auth import user_and_client_from_session
from submit_ce.domain.exceptions import SaveError


logger = logging.getLogger(__name__)  # pylint: disable=C0103

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103


class WithdrawalForm(csrf.CSRFForm, FieldMixin):
    """Submit a withdrawal request."""

    comment = TextAreaField(
        'Comment',
        validators=[DataRequired(), Length(min=10, max=400)],
        description='Limit 400 characters'
    )
    abstract = TextAreaField(
        'Abstract',
        validators=[DataRequired(), Length(min=10, max=1920)],
        description='Limit 1920 characters'
    )
    confirmed = BooleanField('Confirmed',
                             false_values=('false', False, 0, '0', ''))


def request_withdrawal(method: str, params: MultiDict, session: Session,
                       submission_id: str, **kwargs) -> Response:
    """Request withdrawal of a paper."""

    submitter, client = user_and_client_from_session(session)
    logger.debug(f'method: {method}, submission: {submission_id}. {params}')

    # Will raise NotFound if there is no such submission.
    submission_to_wdr, _ = get_submission(submission_id)
    # The submission must be announced for this to be a withdrawal request.
    if not submission_to_wdr.is_announced:
        alerts.flash_failure(Markup(
            "Submission must first be announced. See "
            "<a href='https://arxiv.org/help/withdraw'>the arXiv help pages"
            "</a> for details."
        ))
        loc = url_for('ui.create_submission')
        return {}, status.SEE_OTHER, {'Location': loc}

    if method != 'GET' and method != 'POST':
        return {}, status.OK, {}

    submission = submission_to_wdr
    if method == 'GET':
        params.setdefault("confirmed", False)
        params.setdefault("abstract", submission.metadata.abstract)
        params.setdefault("comments", submission.metadata.comments)

    form = WithdrawalForm(params)
    response_data = {
        'submission_id': submission.submission_id,
        'submission': submission,
        'form': form,
    }
    if method == 'GET' or \
       (method =='POST' and not form.validate()) or \
       (method =='POST' and form.validate() and not form.data['confirmed']):
        response_data['require_confirmation'] = True

        return response_data, status.OK, {}
    elif method == 'POST' and form.validate() and form.data['confirmed']:
        cmd = Withdraw(paper_id=submission_to_wdr.arxiv_id,
                       comments=form.comment.data, abstract=form.abstract.data,
                       creator=submitter, client=client)
        if validate_command(form, cmd, submission_to_wdr):
            try:
                submission_to_wdr, _ = current_app.api.save(cmd)
                response_data['require_confirmation'] = True
                alerts.flash_success("Withdrawal request submitted.")
                status_url = url_for('ui.create_submission')
                return {}, status.SEE_OTHER, {'Location': status_url}
            except SaveError as ex:
                raise InternalServerError(response_data) from ex
    else:
        # kind of unexpected, we should not get here?
        return response_data, status.OK, {}
