"""Controller for cross-list requests."""

from http import HTTPStatus as status
from typing import Tuple, Dict, Any, Optional, List

from arxiv.auth.domain import Session
from flask import url_for
from markupsafe import Markup
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError, BadRequest
from wtforms import widgets
from wtforms.fields import Field, BooleanField, HiddenField
from wtforms.validators import ValidationError, optional

from arxiv.base import logging, alerts
from arxiv.forms import csrf
from submit_ce.ui.backend import save, Submission
from submit_ce.ui.domain.event import RequestCrossList
from submit_ce.ui.exceptions import SaveError
from arxiv.taxonomy.definitions import CATEGORIES_ACTIVE as CATEGORIES
from arxiv.taxonomy.definitions import ARCHIVES_ACTIVE as ARCHIVES

from submit_ce.ui.util import load_submission
from .util import user_and_client_from_session, OptGroupSelectField, \
    validate_command

logger = logging.getLogger(__name__)  # pylint: disable=C0103

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103


CONTACT_SUPPORT = Markup(
    'If you continue to experience problems, please contact'
    ' <a href="mailto:help@arxiv.org"> arXiv support</a>.'
)


class HiddenListField(HiddenField):
    def process_formdata(self, valuelist):
        self.data = list(str(x) for x in valuelist if x)

    def process_data(self, value):
        try:
            self.data = list(str(v) for v in value if v)
        except (ValueError, TypeError):
            self.data = None

    def _value(self):
        return ",".join(self.data) if self.data else ""


class CrossListForm(csrf.CSRFForm):
    """Submit a cross-list request."""

    CATEGORIES = [
        (archive.id, [
            (category_id, f"{category.full_name} ({category_id})")
            for category_id, category in CATEGORIES.items()
            if category.in_archive == archive_id
        ])
        for archive_id, archive in ARCHIVES.items()
    ]
    """Categories grouped by archive."""

    ADD = 'add'
    REMOVE = 'remove'
    OPERATIONS = [
        (ADD, 'Add'),
        (REMOVE, 'Remove')
    ]
    operation = HiddenField(default=ADD, validators=[optional()])
    category = OptGroupSelectField('Category', choices=CATEGORIES,
                                   default='', validators=[optional()])
    selected = HiddenListField()
    confirmed = BooleanField('Confirmed',
                             false_values=('false', False, 0, '0', ''))

    def validate_selected(form: csrf.CSRFForm, field: Field) -> None:
        if form.confirmed.data and not field.data:
            raise ValidationError('Please select a category')
        for value in field.data:
            if value not in CATEGORIES:
                raise ValidationError('Not a valid category')

    def validate_category(form: csrf.CSRFForm, field: Field) -> None:
        if not form.confirmed.data and not field.data:
            raise ValidationError('Please select a category')

    def filter_choices(self, submission: Submission, session: Session,
                       exclude: Optional[List[str]] = None) -> None:
        """Remove redundant choices, and limit to endorsed categories."""
        selected: List[str] = self.category.data
        primary = submission.primary_classification

        choices = [
            (archive, [
                (category, display) for category, display in archive_choices
                if (exclude is not None and category not in exclude
                    and (primary is None or category != primary.category)
                    and category not in submission.secondary_categories)
                or category in selected
            ])
            for archive, archive_choices in self.category.choices
        ]
        self.category.choices = [
            (archive, _choices) for archive, _choices in choices
            if len(_choices) > 0
        ]

    @classmethod
    def formset(cls, selected: List[str]) -> Dict[str, 'CrossListForm']:
        """Generate a set of forms to add/remove categories in the template."""
        formset = {}
        for category in selected:
            if not category:
                continue
            subform = cls(operation=cls.REMOVE, category=category)
            subform.category.widget = widgets.HiddenInput()
            formset[category] = subform
        return formset


def request_cross(method: str, params: MultiDict, session: Session,
                  submission_id: int, **kwargs) -> Response:
    """Request cross-list classification for an announced e-print."""
    submitter, client = user_and_client_from_session(session)
    logger.debug(f'method: {method}, submission: {submission_id}. {params}')

    # Will raise NotFound if there is no such submission.
    submission, submission_events = load_submission(submission_id)

    # The submission must be announced for this to be a cross-list request.
    if not submission.is_announced:
        alerts.flash_failure(
            Markup("Submission must first be announced. See <a"
                   " href='https://arxiv.org/help/cross'>the arXiv help"
                   " pages</a> for details."))
        status_url = url_for('ui.create_submission')
        return {}, status.SEE_OTHER, {'Location': status_url}

    if method == 'GET':
        params = MultiDict({})

    params.setdefault("confirmed", False)
    params.setdefault("operation", CrossListForm.ADD)
    form = CrossListForm(params)
    selected = [v for v in form.selected.data if v]
    form.filter_choices(submission, session, exclude=selected)

    response_data = {
        'submission_id': submission_id,
        'submission': submission,
        'form': form,
        'selected': selected,
        'formset': CrossListForm.formset(selected)
    }
    if submission.primary_classification:
        response_data['primary'] = \
            CATEGORIES[submission.primary_classification.category]

    if method == 'POST':
        if not form.validate():
            raise BadRequest(response_data)

        if form.confirmed.data:     # Stop adding new categories, and submit_ce.
            response_data['form'].operation.data = CrossListForm.ADD
            response_data['require_confirmation'] = True

            command = RequestCrossList(creator=submitter, client=client,
                                       categories=form.selected.data)
            if not validate_command(form, command, submission, 'category'):
                alerts.flash_failure(Markup(
                    "There was a problem with your request. Please try again."
                    f" {CONTACT_SUPPORT}"
                ))
                raise BadRequest(response_data)

            try:    # Submit the cross-list request.
                save(command, submission_id=submission_id)
            except SaveError as e:
                # This would be due to a database error, or something else
                # that likely isn't the user's fault.
                logger.error('Could not save cross list request event')
                alerts.flash_failure(Markup(
                    "There was a problem processing your request. Please try"
                    f" again. {CONTACT_SUPPORT}"
                ))
                raise InternalServerError(response_data) from e

            # Success! Send user back to the submission page.
            alerts.flash_success("Cross-list request submitted.")
            status_url = url_for('ui.create_submission')
            return {}, status.SEE_OTHER, {'Location': status_url}
        else:   # User is adding or removing a category.
            if form.operation.data:
                if form.operation.data == CrossListForm.REMOVE:
                    selected.remove(form.category.data)
                elif form.operation.data == CrossListForm.ADD:
                    selected.append(form.category.data)
                # Update the "remove" formset to reflect the change.
                response_data['formset'] = CrossListForm.formset(selected)
                response_data['selected'] = selected
            # Now that we've handled the request, get a fresh form for adding
            # more categories or submitting the request.
            response_data['form'] = CrossListForm()
            response_data['form'].filter_choices(submission, session,
                                                 exclude=selected)
            response_data['form'].operation.data = CrossListForm.ADD
            response_data['require_confirmation'] = True
            return response_data, status.OK, {}
    return response_data, status.OK, {}
