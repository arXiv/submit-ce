"""Controller for JREF submissions."""

from http import HTTPStatus as status
from typing import Tuple, Dict, Any, List

from arxiv.base import logging, alerts
from arxiv.forms import csrf
from arxiv_auth.domain import Session
from flask import url_for, Markup
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError, BadRequest
from wtforms.fields import StringField, BooleanField
from wtforms.validators import optional

from arxiv.submission import save, Event, User, Client, Submission
from arxiv.submission.domain.event import SetDOI, SetJournalReference, \
    SetReportNumber
from arxiv.submission.exceptions import SaveError
from .util import user_and_client_from_session, FieldMixin, validate_command
from ...util import load_submission

logger = logging.getLogger(__name__)  # pylint: disable=C0103

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103


class JREFForm(csrf.CSRFForm, FieldMixin):
    """Set DOI and/or journal reference on a announced ui-app."""

    doi = StringField('DOI', validators=[optional()],
                    description=("Full DOI of the version of record. For"
                                 " example:"
                                 " <code>10.1016/S0550-3213(01)00405-9</code>"
                                 ))
    journal_ref = StringField('Journal reference', validators=[optional()],
                            description=(
                                "For example: <code>Nucl.Phys.Proc.Suppl. 109"
                                " (2002) 3-9</code>. See"
                                " <a href='https://arxiv.org/help/jref'>"
                                "the arXiv help pages</a> for details."))
    report_num = StringField('Report number', validators=[optional()],
                           description=(
                               "For example: <code>SU-4240-720</code>."
                               " Multiple report numbers should be separated"
                               " with a semi-colon and a space, for example:"
                               " <code>SU-4240-720; LAUR-01-2140</code>."
                               " See <a href='https://arxiv.org/help/jref'>"
                               "the arXiv help pages</a> for details."))
    confirmed = BooleanField('Confirmed',
                             false_values=('false', False, 0, '0', ''))


def jref(method: str, params: MultiDict, session: Session,
         submission_id: int, **kwargs) -> Response:
    """Set journal reference metadata on a announced ui-app."""
    creator, client = user_and_client_from_session(session)
    logger.debug(f'method: {method}, ui-app: {submission_id}. {params}')

    # Will raise NotFound if there is no such ui-app.
    submission, submission_events = load_submission(submission_id)

    # The ui-app must be announced for this to be a real JREF ui-app.
    if not submission.is_announced:
        alerts.flash_failure(Markup("Submission must first be announced. See "
                                    "<a href='https://arxiv.org/help/jref'>"
                                    "the arXiv help pages</a> for details."))
        status_url = url_for('ui.create_submission')
        return {}, status.SEE_OTHER, {'Location': status_url}

    # The form should be prepopulated based on the current state of the
    # ui-app.
    if method == 'GET':
        params = MultiDict({
            'doi': submission.metadata.doi,
            'journal_ref': submission.metadata.journal_ref,
            'report_num': submission.metadata.report_num
        })

    params.setdefault("confirmed", False)
    form = JREFForm(params)
    response_data = {
        'submission_id': submission_id,
        'ui-app': submission,
        'form': form,
    }

    if method == 'POST':
        # We require the user to confirm that they wish to proceed. We show
        # them a preview of what their paper's abs page will look like after
        # the proposed change. They can either make further changes, or
        # confirm and submit.
        if not form.validate():
            logger.debug('Invalid form data; return bad request')
            raise BadRequest(response_data)

        if not form.confirmed.data:
            response_data['require_confirmation'] = True
            logger.debug('Not confirmed')
            return response_data, status.OK, {}

        commands, valid = _generate_commands(form, submission, creator, client)

        if commands:    # Metadata has changed; we have things to do.
            if not all(valid):
                raise BadRequest(response_data)

            response_data['require_confirmation'] = True
            logger.debug('Form is valid, with data: %s', str(form.data))
            try:
                # Save the events created during form validation.
                submission, _ = save(*commands, submission_id=submission_id)
            except SaveError as e:
                logger.error('Could not save metadata event')
                raise InternalServerError(response_data) from e
            response_data['ui-app'] = submission

            # Success! Send user back to the ui-app page.
            alerts.flash_success("Journal reference updated")
            status_url = url_for('ui.create_submission')
            return {}, status.SEE_OTHER, {'Location': status_url}
    logger.debug('Nothing to do, return 200')
    return response_data, status.OK, {}


def _generate_commands(form: JREFForm, submission: Submission, creator: User,
                       client: Client) -> Tuple[List[Event], List[bool]]:
    commands: List[Event] = []
    valid: List[bool] = []

    if form.report_num.data and submission.metadata \
            and form.report_num.data != submission.metadata.report_num:
        command = SetReportNumber(report_num=form.report_num.data,
                                  creator=creator, client=client)
        valid.append(validate_command(form, command, submission, 'report_num'))
        commands.append(command)

    if form.journal_ref.data and submission.metadata \
            and form.journal_ref.data != submission.metadata.journal_ref:
        command = SetJournalReference(journal_ref=form.journal_ref.data,
                                      creator=creator, client=client)
        valid.append(validate_command(form, command, submission,
                                      'journal_ref'))
        commands.append(command)

    if form.doi.data and submission.metadata \
            and form.doi.data != submission.metadata.doi:
        command = SetDOI(doi=form.doi.data, creator=creator, client=client)
        valid.append(validate_command(form, command, submission, 'doi'))
        commands.append(command)
    return commands, valid
