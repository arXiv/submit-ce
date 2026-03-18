"""Provides a controller for updating metadata on a submission."""

from typing import Tuple, Dict, Any, List

from werkzeug.datastructures import MultiDict
from wtforms.fields import StringField, TextAreaField
from wtforms import validators
from flask import current_app
import logging

from http import HTTPStatus as status
from arxiv.forms import csrf
from arxiv.auth.domain import Session

from submit_ce.ui.auth import user_and_client_from_session

from submit_ce.domain.agent import Client, User
from submit_ce.domain import Submission, Event
from submit_ce.domain.event import SetTitle, SetAuthors, SetAbstract,SetACMClassification, SetMSCClassification, SetComments, SetReportNumber, SetJournalReference, SetDOI

from submit_ce.ui.backend import get_submission
from submit_ce.ui.controllers.util import validate_command, FieldMixin
from submit_ce.ui.routes.flow_control import ready_for_next, stay_on_this_stage





logger = logging.getLogger(__name__)  # pylint: disable=C0103

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103


class MetadataForm(csrf.CSRFForm, FieldMixin):
    """Handles metadata fields on a submission."""

    title = StringField('Title', validators=[validators.DataRequired()])
    authors_display = TextAreaField(
        'Authors',
        validators=[validators.DataRequired()],
        description=("use <code>GivenName(s) FamilyName(s)</code> or <code>I. "
                     "FamilyName</code>; separate individual authors with "
                     "a comma or 'and'.")
    )
    abstract = TextAreaField('Abstract',
                             validators=[validators.DataRequired()],
                             description='Limit of 1920 characters')
    comments = StringField('Comments',
                         default='',
                         validators=[validators.optional()],
                         description=(
                            "Supplemental information such as number of pages "
                            "or figures, conference information."
                         ))
    doi = StringField('DOI',
                    validators=[validators.optional()],
                    description="Full DOI of the version of record.")

    journal_ref = StringField('Journal reference',
                            validators=[validators.optional()],
                            description=(
                                "See <a href='https://arxiv.org/help/jref'>"
                                "the arXiv help pages</a> for details."
                            ))
    report_num = StringField('Report number',
                           validators=[validators.optional()],
                           description=(
                               "See <a href='https://arxiv.org/help/jref'>"
                               "the arXiv help pages</a> for details."
                           ))
    acm_class = StringField('ACM classification',
                          validators=[validators.optional()],
                          description="example: F.2.2; I.2.7")

    msc_class = StringField('MSC classification',
                          validators=[validators.optional()],
                          description=("example: 14J60 (Primary), 14F05, "
                                       "14J26 (Secondary)"))


def _data_from_submission(params: MultiDict, submission: Submission,
                          form_class: type) -> MultiDict:
    if not submission.metadata:
        return params
    for field in form_class.fields():
        params[field] = getattr(submission.metadata, field, '')
    return params


def metadata(method: str, params: MultiDict, session: Session,
             submission_id: int, **kwargs) -> Response:
    """Update submission metadata on the submission."""
    submitter, client = user_and_client_from_session(session)
    logger.debug(f'method: {method}, submission: {submission_id}. {params}')
    submission, submission_events = get_submission(submission_id)

    if method == 'GET':
        params = _data_from_submission(params, submission, MetadataForm)
    form = MetadataForm(params)
    response_data = {
        'submission_id': submission_id,
        'form': form,
        'submission': submission
    }
    if method == 'GET':
        return response_data, status.OK, {}
    if method != 'POST':
        return response_data, status.METHOD_NOT_ALLOWED, {}

    validate = form.validate()
    if not validate:
        return stay_on_this_stage((response_data, status.BAD_REQUEST, {}))
    changes, valid = _commands(form, submission, submitter, client)
    if not changes:
        return ready_for_next((response_data, status.OK, {}))

    if not changes or not all(valid):   # Metadata has changed and is valid
        return stay_on_this_stage((response_data, status.BAD_REQUEST, {}))

    submission, _ = current_app.api.save(*changes, submission_id=submission_id)
    response_data['submission'] = submission
    return ready_for_next((response_data, status.OK, {}))


def _commands(form: MetadataForm, submission: Submission,
              creator: User, client: Client) -> Tuple[List[Event], List[bool]]:
    commands: List[Event] = []
    valid: List[bool] = []

    if form.title.data and submission.metadata \
            and form.title.data != submission.metadata.title:
        command = SetTitle(title=form.title.data, creator=creator,
                           client=client)
        valid.append(validate_command(form, command, submission, 'title'))
        commands.append(command)

    if form.abstract.data and submission.metadata \
            and form.abstract.data != submission.metadata.abstract:
        command = SetAbstract(abstract=form.abstract.data, creator=creator,
                              client=client)
        valid.append(validate_command(form, command, submission, 'abstract'))
        commands.append(command)

    if form.comments.data and submission.metadata \
            and form.comments.data != submission.metadata.comments:
        command = SetComments(comments=form.comments.data, creator=creator,
                              client=client)
        valid.append(validate_command(form, command, submission, 'comments'))
        commands.append(command)

    value = form.authors_display.data
    if value and submission.metadata \
            and value != submission.metadata.authors_display:
        command = SetAuthors(authors_display=form.authors_display.data,
                             creator=creator, client=client)
        valid.append(validate_command(form, command, submission,
                                      'authors_display'))
        commands.append(command)

    # #################### OPTIONAL FIELDS #################### #

    if form.msc_class.data and submission.metadata \
            and form.msc_class.data != submission.metadata.msc_class:
        command = SetMSCClassification(msc_class=form.msc_class.data,
                                       creator=creator, client=client)
        valid.append(validate_command(form, command, submission, 'msc_class'))
        commands.append(command)

    if form.acm_class.data and submission.metadata \
            and form.acm_class.data != submission.metadata.acm_class:
        command = SetACMClassification(acm_class=form.acm_class.data,
                                       creator=creator, client=client)
        valid.append(validate_command(form, command, submission, 'acm_class'))
        commands.append(command)

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
