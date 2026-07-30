"""Controllers for JREF submissions.

A journal reference is its own submission, so there are two controllers,
mirroring legacy:

- :func:`add_jref` -- create one, keyed on the *announced* submission
  (legacy ``/user/<doc>/jref``).
- :func:`jref` -- edit one, keyed on the *jref's own* submission
  (legacy ``/submit/<id>/jref``).
"""

from http import HTTPStatus as status
from typing import Tuple, Dict, Any, List, Optional

from arxiv.auth.domain import Session
from flask import url_for, current_app
from markupsafe import Markup
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError, BadRequest, NotFound
from wtforms.fields import BooleanField
from wtforms.fields.simple import StringField
from wtforms.validators import optional

from arxiv.base import logging, alerts
from arxiv.forms import csrf
from submit_ce.domain import  Event, User, Client, Submission
from submit_ce.domain.event import CreateJrefSubmission, SetDOI, \
    SetJournalReference
from submit_ce.domain.exceptions import InvalidEvent, NoSuchDocument, SaveError
from submit_ce.domain.event import SetReportNumber
from submit_ce.domain.submission import SubmissionType
from submit_ce.ui.backend import get_submission
from ..auth import user_and_client_from_session
from .util import FieldMixin, validate_command


logger = logging.getLogger(__name__)  # pylint: disable=C0103

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103


class AddJREFForm(csrf.CSRFForm):
    """No fields; exists only to CSRF-protect the create POST.

    The token is bound to the session nonce and the remote address rather than
    to a set of fields (see ``arxiv.forms.csrf``), so the token rendered on the
    dashboard -- where the button lives -- validates here.
    """


class JREFForm(csrf.CSRFForm, FieldMixin):
    """Set DOI and/or journal reference on a announced submission."""

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


def _active_submission_id(paper_id: str,
                          submission_type: Optional[SubmissionType] = None) \
        -> Optional[str]:
    """Id of the paper's in-progress submission, if it has one.

    A paper gets one active submission at a time, so this answers both of the
    questions :func:`add_jref` asks. Pass ``submission_type`` to count only
    submissions of that type -- an in-progress journal reference is one to
    resume, where an in-progress anything-else is one that blocks. With no
    type, any in-progress submission counts.

    Returns ``None`` for a paper that does not exist, leaving the caller to
    decide whether that is a 404 or just nothing to resume.
    """
    try:
        document = current_app.api.get_document(paper_id)
    except NoSuchDocument:
        return None
    for sub in document.active_submissions:
        if submission_type is None or sub.submission_type == submission_type:
            return str(sub.submission_id)
    return None


def add_jref(method: str, params: MultiDict, session: Session,
             submission_id: Optional[str] = None,
             paper_id: Optional[str] = None) -> Response:
    """Create a journal reference submission for an announced paper.

    ``paper_id`` is the *announced* paper being annotated; ``submission_id`` is
    unused and only here to match the controller signature ``handle()`` calls
    with. On success a new jref submission is created and the user is
    redirected to its own edit page (:func:`jref`), where the journal
    reference, DOI and report number are entered.

    Creating a submission is a write, so this is POST only.
    """
    if method != 'POST':
        return {}, status.METHOD_NOT_ALLOWED, {}
    if not paper_id:
        return {}, status.BAD_REQUEST, {}
    if not AddJREFForm(params).validate():
        raise BadRequest('Invalid or missing CSRF token')

    # A paper gets one journal reference at a time, so a second press of the
    # button (or a browser refresh) resumes the one already in progress rather
    # than failing on `CreateJrefSubmission.validate_under_lock`.
    existing = _active_submission_id(paper_id,
                                     SubmissionType.JOURNAL_REFERENCE)
    if existing is not None:
        logger.debug('Paper %s already has jref %s', paper_id, existing)
        return {}, status.SEE_OTHER, {
            'Location': url_for('ui.jref', submission_id=existing)}

    creator, client = user_and_client_from_session(session)
    command = CreateJrefSubmission(creator=creator, client=client,
                                   paper_id=paper_id)
    try:
        jref_submission, _ = current_app.api.save(command)
    except NoSuchDocument as e:
        raise NotFound(f'No such paper: {paper_id}') from e
    except InvalidEvent:
        # The paper has some other submission in progress (a replacement, a
        # withdrawal, a cross-list), so it cannot take a journal reference yet.
        logger.debug('Paper %s cannot take a jref right now', paper_id)
        # Re-read rather than reuse the lookup above: the rejection came from
        # under the row lock, so this is the fresher answer.
        return ({'conflicting_submission_id': _active_submission_id(paper_id)},
                status.OK, {})
    except SaveError as e:
        logger.error('Could not save jref submission')
        raise InternalServerError("Could not start jref submission") from e

    return {}, status.SEE_OTHER, {
        'Location': url_for(
            'ui.jref',
            submission_id=jref_submission.submission_id)}


def jref(method: str, params: MultiDict, session: Session,
         submission_id: str, **kwargs) -> Response:
    """Edit an existing journal reference submission.

    ``submission_id`` is the *jref's own* submission id. Use
    :func:`add_jref` to create one.
    """
    creator, client = user_and_client_from_session(session)
    logger.debug(f'method: {method}, submission: {submission_id}. {params}')

    # Will raise NotFound if there is no such submission.
    submission, submission_events = get_submission(submission_id)

    # This endpoint edits a jref; it does not create one.
    if submission.submission_type != SubmissionType.JOURNAL_REFERENCE:
        alerts.flash_failure(Markup(
            "That is not a journal reference submission. See "
            "<a href='https://arxiv.org/help/jref'>the arXiv help pages</a>"
            " for details."))
        status_url = url_for('ui.create_submission')
        return {}, status.SEE_OTHER, {'Location': status_url}

    # The form should be prepopulated based on the current state of the
    # submission.
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
        'submission': submission,
        'form': form,
        'form_action': 'ui.jref',
    }

    if method == 'POST':
        # We require the user to confirm that they wish to proceed. We show
        # them a preview of what their paper's abs page will look like after
        # the proposed change. They can either make further changes, or
        # confirm and submit_ce.
        if not form.validate():
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
                submission, _ = current_app.api.save(*commands, submission_id=submission_id)
            except SaveError as e:
                logger.error('Could not save metadata event')
                raise InternalServerError(response_data) from e
            response_data['submission'] = submission

            # Success! Send user back to the submission page.
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
