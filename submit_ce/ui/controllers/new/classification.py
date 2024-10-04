"""
Controller for classification actions.
"""
from typing import Tuple, Dict, Any

from arxiv.auth.domain import Session
from arxiv.taxonomy.definitions import ARCHIVES_ACTIVE, CATEGORIES_ACTIVE, CATEGORIES
from flask import request
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError
from wtforms import widgets, HiddenField, validators

from http import HTTPStatus as status
from arxiv import taxonomy
from arxiv.forms import csrf
from arxiv.base import alerts

from submit_ce.api.domain import Submission
from submit_ce.api.domain.events import SetCategories
from submit_ce.ui.backend import save, endorsed_for, get_client, get_user, api, impl_data
from submit_ce.ui.exceptions import SaveError

from submit_ce.ui.controllers.util import validate_command, OptGroupSelectField
from submit_ce.ui.routes.flow_control import ready_for_next, stay_on_this_stage

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103


class ClassificationForm(csrf.CSRFForm):
    """Form for classification selection."""

    CATEGORIES = [
        (archive.id, [
            (category_id, f"{category.full_name} ({category_id})")
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

    def filter_choices(self, submission: Submission, session: Session) -> None:
        """Remove redundant choices, and limit to endorsed categories."""
        selected = self.category.data
        primary = submission.primary_classification

        choices = [
            (archive, [
                (category, display) for category, display in archive_choices
                if endorsed_for(session, category)
                and (((primary is None or category != primary.category)
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
    submitter, client = get_user(), get_client()
    submission: Submission = request.submission

    if method == 'GET':
        params.setdefault('category', session.user.profile.default_category)
        if submission.primary_classification and submission.primary_classification.category:
            params['category'] = submission.primary_classification.category

    params['operation'] = PrimaryClassificationForm.ADD

    form = PrimaryClassificationForm(params)
    form.filter_choices(submission, request.auth)

    response_data = {
        'submission_id': submission_id,
        'submission': submission,
        'submitter': submitter,
        'client': client,
        'form': form
    }

    # command = SetPrimaryClassification(category=form.category.data,
    #                                    creator=submitter, client=client)
    # if method == 'POST' and form.validate()\
    #    and validate_command(form, command, submission, 'category'):
    #     try:
    #         submission, _ = save(command, submission_id=submission_id)
    #         response_data['submission'] = submission
    #     except SaveError as ex:
    #         raise InternalServerError(response_data) from ex
    #     return ready_for_next((response_data, status.OK, {}))
    if method == 'POST' and form.validate():
        api.set_categories_post(impl_data(), get_user(), get_client(),
                                submission_id, SetCategories(primary_category=form.category.data))

    return response_data, status.OK, {}


def cross_list(method: str, params: MultiDict, session: Session,
               submission_id: int, **kwargs) -> Response:
    """Handle secondary classification requests for a new submision."""
    submitter, client = get_user(), get_client()
    submission = request.submission

    form = ClassificationForm(params)
    form.operation._value = lambda: form.operation.data
    form.filter_choices(submission, request.auth)

    # Create a formset to render removal option.
    #
    # We need forms for existing secondaries, to generate removal requests.
    # When the forms in the formset are submitted, they are handled as the
    # primary form in the POST request to this controller.
    formset = ClassificationForm.formset(submission)
    _primary_category = submission.primary_classification.category
    _primary = CATEGORIES[_primary_category]

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

    # if form.operation.data == form.REMOVE:
    #     command_type = RemoveSecondaryClassification
    # else:
    #     command_type = AddSecondaryClassification
    # command = command_type(category=form.category.data,
    #                        creator=submitter, client=client)
    if method == 'POST' and form.validate():
       #and validate_command(form, command, submission, 'category'):
        # try:
        #     submission, _ = save(command, submission_id=submission_id)
        #     response_data['submission'] = submission
        #
        #     # Re-build the formset to reflect changes that we just made, and
        #     # generate a fresh form for adding another secondary. The POSTed
        #     # data should now be reflected in the formset.
        #     response_data['formset'] = ClassificationForm.formset(submission)
        #     form = ClassificationForm()
        #     form.operation._value = lambda: form.operation.data
        #     form.filter_choices(submission, request.auth)
        #     response_data['form'] = form
        #
        #     # do not go to next yet, re-show cross form
        #     return stay_on_this_stage((response_data, status.OK, {}))
        # except SaveError as ex:
        #     raise InternalServerError(response_data) from ex

        raise NotImplementedError()
        
    if len(submission.secondary_categories) > 3:
        alerts.flash_warning(Markup(
            'Adding more than three cross-list classifications will'
            ' result in a delay in the acceptance of your submission.'
        ))
    return response_data, status.OK, {}
