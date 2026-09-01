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
    """Handles metadata fields on a submission. QA checks enforce required fields."""

    title = StringField('Title', validators=[validators.optional()])
    authors_display = TextAreaField(
        'Authors',
        validators=[validators.optional()],
        description=("use <code>GivenName(s) FamilyName(s)</code> or <code>I. "
                     "FamilyName</code>; separate individual authors with "
                     "a comma or 'and'.")
    )
    abstract = TextAreaField('Abstract',
                             validators=[validators.optional()],
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
             submission_id: str, **kwargs) -> Response:
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


# Field name, and the Event class whose constructor takes that same name
# as its keyword argument. Whether a field is actually required is decided
# entirely by that field's QA check (its EmptyFieldCheck on_failure_policy),
# not here -- so every field is treated identically below.
_METADATA_FIELDS: List[Tuple[str, type]] = [
    ('title', SetTitle),
    ('abstract', SetAbstract),
    ('comments', SetComments),
    ('authors_display', SetAuthors),
    ('msc_class', SetMSCClassification),
    ('acm_class', SetACMClassification),
    ('report_num', SetReportNumber),
    ('journal_ref', SetJournalReference),
    ('doi', SetDOI),
]


def _commands(form: MetadataForm, submission: Submission,
              creator: User, client: Client) -> Tuple[List[Event], List[bool]]:
    commands: List[Event] = []
    valid: List[bool] = []

    if not submission.metadata:
        return commands, valid

    for field_name, event_cls in _METADATA_FIELDS:
        # A missing key in the POST body (as opposed to an empty string)
        # leaves form.<field>.data as None; treat it the same as blank so
        # an omitted field can't skip its QA check below. Also run the
        # check whenever the field is (still) blank, not just on change,
        # so a field's QA policy can be tightened to require it without
        # also having to change this controller.
        data = getattr(form, field_name).data or ''
        stored = getattr(submission.metadata, field_name)
        if data != stored or not data:
            command = event_cls(creator=creator, client=client,
                                **{field_name: data})
            valid.append(validate_command(form, command, submission, field_name))
            commands.append(command)

    return commands, valid
