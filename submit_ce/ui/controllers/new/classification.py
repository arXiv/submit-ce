"""
Controller for classification actions.

Creates an event of type `core.events.event.SetPrimaryClassification`
Creates an event of type `core.events.event.AddSecondaryClassification`
"""
from http import HTTPStatus as status
from typing import Tuple, Dict, Any

from arxiv import taxonomy
from arxiv.auth.domain import Session
from arxiv.base import alerts
from arxiv.forms import csrf
from arxiv.taxonomy.definitions import CATEGORIES_ACTIVE, ARCHIVES_ACTIVE
from markupsafe import Markup

from submit_ce.api import User
from submit_ce.ui.backend import endorsed_for
from submit_ce.ui.auth import user_and_client_from_session
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError
from wtforms import widgets, HiddenField, validators
from flask import current_app

from submit_ce.api.domain import Submission
from submit_ce.api.domain.event import RemoveSecondaryClassification, \
    AddSecondaryClassification, SetPrimaryClassification
from submit_ce.api.exceptions import SaveError
from submit_ce.ui.controllers.util import OptGroupSelectField, validate_command
from submit_ce.ui.routes.flow_control import ready_for_next, stay_on_this_stage
from submit_ce.ui.backend import get_submission

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103


class ClassificationForm(csrf.CSRFForm):
    """Form for classification selection."""

    CATEGORIES = [
        (archive.id, [
            (category_id, f"{category_id}  {category.full_name}")
            for category_id, category in CATEGORIES_ACTIVE.items()
            if category.in_archive == archive_id
        ])
        for archive_id, archive in ARCHIVES_ACTIVE.items()
    ]
    """Categories grouped by archive."""

    ADD = 'add'
    REMOVE = 'remove'
    OPERATIONS = [
        (ADD, 'Add'),
        (REMOVE, 'Remove')
    ]
    operation = HiddenField(default=ADD, validators=[validators.optional()])
    category = OptGroupSelectField('Category', choices=CATEGORIES, default='')

    def filter_choices(self, submission: Submission, user: User) -> None:
        """Remove redundant choices, and limit to endorsed categories."""

        selected = self.category.data
        primary = submission.primary_classification

        choices = [
            (archive, [
                (category, display) for category, display in archive_choices
                if endorsed_for(user, category) and \
                  (((primary is None or category != primary.category)
                    and category not in submission.secondary_categories)
                   or category == selected)
            ])
            for archive, archive_choices in self.category.choices
        ]
        self.category.choices = [
            (archive, _choices) for archive, _choices in choices
            if len(_choices) > 0
        ]

    @classmethod
    def formset(cls, submission: Submission) \
            -> Dict[str, 'ClassificationForm']:
        """Generate a set of forms used to remove cross-list categories."""
        formset = {}
        if hasattr(submission, 'secondary_classification') and \
                submission.secondary_classification:
            for ix, secondary in enumerate(submission.secondary_classification):
                this_category = str(secondary.category)
                subform = cls(operation=cls.REMOVE, category=this_category)
                subform.category.widget = widgets.HiddenInput()
                subform.category.id = f"{ix}_category"
                subform.operation.id = f"{ix}_operation"
                subform.csrf_token.id = f"{ix}_csrf_token"
                formset[secondary.category] = subform
        return formset


class PrimaryClassificationForm(ClassificationForm):
    """Form for setting the primary classification."""

    def validate_operation(self, field) -> None:
        """Make sure the client isn't monkeying with the operation."""
        if field.data != self.ADD:
            raise validators.ValidationError('Invalid operation')


def classification(method: str, params: MultiDict, session: Session,
                   submission_id: int, **kwargs) -> Response:
    """Handle primary classification requests for a new submission."""
    submitter, client = user_and_client_from_session(session)
    submission, _ = get_submission(submission_id)
    if method == 'GET':
        # Prepopulate the form based on the state of the submission.
        if submission.primary_classification and submission.primary_classification.category:
            params['category'] = submission.primary_classification.category

        # Use the user's default category as the default for the form.
        params.setdefault('category', session.user.profile.default_category)

    params['operation'] = PrimaryClassificationForm.ADD
    form = PrimaryClassificationForm(params)
    form.filter_choices(submission, submitter)
    response_data = {
        'submission_id': submission_id,
        'submission': submission,
        'submitter': submitter,
        'client': client,
        'form': form
    }

    if method != 'POST':
        return response_data, status.OK, {}

    if form.validate():
        command = SetPrimaryClassification(category=form.category.data, creator=submitter, client=client)
        if validate_command(form, command, submission, 'category'):
            try:
                submission, _ = current_app.api.save(command, submission_id=submission_id)
                response_data['submission'] = submission
                return ready_for_next((response_data, status.OK, {}))
            except SaveError as ex:
                raise InternalServerError(response_data) from ex
            finally:
                pass
        else:                                  
            return response_data, status.BAD_REQUEST, {}
    else:
        return response_data, status.BAD_REQUEST, {}
        


def cross_list(method: str, params: MultiDict, session: Session,
               submission_id: int, **kwargs) -> Response:
    """Handle secondary classification requests for a new submission."""
    submitter, client = user_and_client_from_session(session)
    #submission, submission_events = get_submission(submission_id)
    submission, _ = get_submission(submission_id)

    form = ClassificationForm(params)
    form.operation._value = lambda: form.operation.data
    form.filter_choices(submission, submitter)

    # Create a formset to render removal option.
    #
    # We need forms for existing secondaries, to generate removal requests.
    # When the forms in the formset are submitted, they are handled as the
    # primary form in the POST request to this controller.
    formset = ClassificationForm.formset(submission)
    _primary = taxonomy.definitions.CATEGORIES[submission.primary_classification.category]

    response_data = {
        'submission_id': submission_id,
        'submission': submission,
        'submitter': submitter,
        'client': client,
        'form': form,
        'formset': formset,
        'primary': {
            'id': submission.primary_classification.category,
            'name': _primary.full_name,
        },
    }

    # Ensure the user is not attempting to move to a different step.
    # Since the interface provides an "add" button to add cross-list
    # categories, we only want to handle the form data if the user is not
    # attempting to move to a different step.

    if form.operation.data == form.REMOVE:
        command_type = RemoveSecondaryClassification
    else:
        command_type = AddSecondaryClassification
    command = command_type(category=form.category.data,
                           creator=submitter, client=client)
    if method == 'POST' and form.validate() \
       and validate_command(form, command, submission, 'category'):
        try:
            submission, _ = current_app.api.save(command, submission_id=submission_id)
            response_data['submission'] = submission
            
            # Re-build the formset to reflect changes that we just made, and
            # generate a fresh form for adding another secondary. The POSTed
            # data should now be reflected in the formset.
            response_data['formset'] = ClassificationForm.formset(submission)
            form = ClassificationForm()
            form.operation._value = lambda: form.operation.data
            form.filter_choices(submission, submitter)
            response_data['form'] = form

            # do not go to next yet, re-show cross form
            return stay_on_this_stage((response_data, status.OK, {}))
        except SaveError as ex:
            raise InternalServerError(response_data) from ex

        
    if len(submission.secondary_categories) > 3:
        alerts.flash_warning(Markup(
            'Adding more than three cross-list classifications will'
            ' result in a delay in the acceptance of your submission.'
        ))
    return response_data, status.OK, {}
