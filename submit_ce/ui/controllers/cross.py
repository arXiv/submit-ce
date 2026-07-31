"""Controllers for cross-list submissions.

A cross-list is its own submission, so there are two controllers, mirroring
legacy:

- :func:`add_cross` -- create one, keyed on the *announced paper*
  (legacy ``/user/<document_id>/cross``).
- :func:`cross` -- edit one, keyed on the *cross's own* submission
  (legacy ``/submit/<submission_id>/cross``), which is where categories are
  added and removed and where the cross is finally submitted.

This replaces the old request-based flow (``RequestCrossList``), which recorded
the cross as a pending request on the announced submission rather than as a
submission of its own.
"""

from http import HTTPStatus as status
from typing import Tuple, Dict, Any, Optional, List

from arxiv.auth.domain import Session
from flask import url_for, current_app
from markupsafe import Markup
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError, BadRequest, NotFound
from wtforms import widgets
from wtforms.fields import Field, HiddenField
from wtforms.validators import ValidationError, optional

from arxiv.base import logging, alerts
from arxiv.forms import csrf
from arxiv.taxonomy.definitions import CATEGORIES_ACTIVE as CATEGORIES
from arxiv.taxonomy.definitions import ARCHIVES_ACTIVE as ARCHIVES

from submit_ce.domain import Submission
from submit_ce.domain.event import AddCrossCategory, CreateCrossSubmission, \
    FinalizeCrossSubmission, RemoveCrossCategory, UnFinalizeSubmission
from submit_ce.domain.exceptions import InvalidEvent, NoSuchDocument, SaveError
from submit_ce.domain.submission import SubmissionType
from submit_ce.ui import SUPPORT
from submit_ce.ui.backend import get_submission
from ..auth import user_and_client_from_session
from .util import OptGroupSelectField, active_submission_id, \
    prospective_submission, validate_command


logger = logging.getLogger(__name__)  # pylint: disable=C0103

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103


class AddCrossForm(csrf.CSRFForm):
    """No fields; exists only to CSRF-protect the create POST.

    The token is bound to the session nonce and the remote address rather than
    to a set of fields (see ``arxiv.forms.csrf``), so the token rendered on the
    dashboard -- where the button lives -- validates here.
    """


class SubmitCrossForm(csrf.CSRFForm):
    """No fields; CSRF-protects the final submit POST.

    Separate from :class:`CrossListForm` because that form's category select
    validates its value against the choices on offer, and the submit POST
    carries no category at all.
    """


class CrossListForm(csrf.CSRFForm):
    """Add a category to, or remove one from, a cross-list submission."""

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

    def validate_category(self, field: Field) -> None:
        """Every add or remove names a category."""
        if not field.data:
            raise ValidationError('Please select a category')
        if field.data not in CATEGORIES:
            raise ValidationError('Not a valid category')

    def filter_choices(self, submission: Submission) -> None:
        """Offer the categories that could still be added, plus the pending ones.

        Dropping what is already on the submission keeps the add select honest.
        The categories this cross is adding stay on the list even so, because
        the select also validates a *remove* POST's value
        (:meth:`.OptGroupSelectField.pre_validate`).
        """
        primary = submission.primary_classification
        pending = submission.new_cross_categories
        choices = [
            (archive, [
                (category, display) for category, display in archive_choices
                if ((primary is None or category != primary.category)
                    and category not in submission.secondary_categories)
                or category in pending
            ])
            for archive, archive_choices in self.category.choices
        ]
        self.category.choices = [
            (archive, _choices) for archive, _choices in choices
            if len(_choices) > 0
        ]

    @classmethod
    def formset(cls, categories: List[str]) -> Dict[str, 'CrossListForm']:
        """A remove-form per category, for the template."""
        formset = {}
        for category in categories:
            if not category:
                continue
            subform = cls(operation=cls.REMOVE, category=category)
            subform.category.widget = widgets.HiddenInput()
            formset[category] = subform
        return formset


def add_cross(method: str, params: MultiDict, session: Session,
              submission_id: Optional[str] = None,
              paper_id: Optional[str] = None) -> Response:
    """Create a cross-list submission for an announced paper.

    ``paper_id`` is the *announced* paper being cross-listed; ``submission_id``
    is unused and only here to match the controller signature ``handle()`` calls
    with. On success a new cross submission is created and the user is
    redirected to its own edit page (:func:`cross`), where categories are chosen.

    Creating a submission is a write, so this is POST only.
    """
    if method != 'POST':
        return {}, status.METHOD_NOT_ALLOWED, {}
    if not paper_id:
        return {}, status.BAD_REQUEST, {}
    if not AddCrossForm(params).validate():
        raise BadRequest('Invalid or missing CSRF token')

    # A paper gets one cross-list at a time, so a second press of the button (or
    # a browser refresh) resumes the one already in progress rather than failing
    # on `CreateCrossSubmission.validate_under_lock`.
    existing = active_submission_id(paper_id, SubmissionType.CROSS_LIST)
    if existing is not None:
        logger.debug('Paper %s already has cross %s', paper_id, existing)
        return {}, status.SEE_OTHER, {
            'Location': url_for('ui.cross', submission_id=existing)}

    creator, client = user_and_client_from_session(session)
    command = CreateCrossSubmission(creator=creator, client=client,
                                    paper_id=paper_id)
    try:
        cross_submission, _ = current_app.api.save(command)
    except NoSuchDocument as e:
        raise NotFound(f'No such paper: {paper_id}') from e
    except InvalidEvent as e:
        # Either the paper has some other submission in progress, or it is not
        # eligible for cross-listing at all (a general primary category, or
        # already at the secondary-category limit).
        logger.debug('Paper %s cannot take a cross right now: %s', paper_id, e)
        # Re-read rather than reuse the lookup above: the rejection came from
        # under the row lock, so this is the fresher answer.
        return ({'conflicting_submission_id': active_submission_id(paper_id),
                 'reason': e.message},
                status.OK, {})
    except SaveError as e:
        logger.error('Could not save cross submission')
        raise InternalServerError("Could not start cross-list submission") from e

    return {}, status.SEE_OTHER, {
        'Location': url_for('ui.cross',
                            submission_id=cross_submission.submission_id)}


def cross(method: str, params: MultiDict, session: Session,
          submission_id: str, **kwargs) -> Response:
    """Edit an existing cross-list submission.

    ``submission_id`` is the *cross's own* submission id. Use :func:`add_cross`
    to create one. Three POSTs are handled: add a category, remove one of the
    categories this cross is adding, and submit.
    """
    creator, client = user_and_client_from_session(session)
    logger.debug(f'method: {method}, submission: {submission_id}. {params}')

    # Will raise NotFound if there is no such submission.
    submission, _ = get_submission(submission_id)

    # This endpoint edits a cross-list; it does not create one.
    if submission.submission_type != SubmissionType.CROSS_LIST:
        alerts.flash_failure(Markup(
            "That is not a cross-list submission. See "
            "<a href='https://arxiv.org/help/cross'>the arXiv help pages</a>"
            " for details."))
        return {}, status.SEE_OTHER, {
            'Location': url_for('ui.manage_submissions')}

    if method == 'GET':
        params = MultiDict({})

    # The page renders from the submission's saved state, so the form in the
    # context is always a fresh add form -- never the one a submit POST used.
    response_data = _response_data(submission, submission_id,
                                   _add_form(submission))

    if method != 'POST':
        return response_data, status.OK, {}

    if params.get('confirmed'):
        submit_form = SubmitCrossForm(params)
        if not submit_form.validate():
            raise BadRequest(response_data)
        return _submit_cross(submit_form, submission, submission_id, creator,
                             client, response_data)

    params.setdefault("operation", CrossListForm.ADD)
    form = CrossListForm(params)
    form.filter_choices(submission)
    if not form.validate():
        raise BadRequest(response_data)
    return _edit_categories(form, submission, submission_id, creator, client,
                            response_data)


def _add_form(submission: Submission) -> CrossListForm:
    """A blank add-a-category form for the categories still on offer."""
    form = CrossListForm()
    form.filter_choices(submission)
    form.operation.data = CrossListForm.ADD
    return form


def _response_data(submission: Submission, submission_id: str,
                   form: CrossListForm) -> Dict[str, Any]:
    """The template context, rebuilt from the submission's current state.

    The categories being added live on the submission (as unpublished secondary
    classifications), not in a hidden form field, so every render reads them
    back from the saved state.
    """
    new_categories = submission.new_cross_categories
    data: Dict[str, Any] = {
        'submission_id': submission_id,
        'submission': submission,
        'form': form,
        'new_categories': new_categories,
        'published_categories': [c.category
                                 for c in submission.secondary_classification
                                 if c.is_published],
        'formset': CrossListForm.formset(new_categories),
        'require_confirmation': bool(new_categories),
    }
    if submission.primary_classification:
        data['primary'] = CATEGORIES[submission.primary_classification.category]
    return data


def _edit_categories(form: CrossListForm, submission: Submission,
                     submission_id: str, creator, client,
                     response_data: Dict[str, Any]) -> Response:
    """Add or remove one of the categories this cross is proposing."""
    category = form.category.data
    if form.operation.data == CrossListForm.REMOVE:
        command = RemoveCrossCategory(creator=creator, client=client,
                                     category=category)
    else:
        command = AddCrossCategory(creator=creator, client=client,
                                   category=category)

    # Legacy unsubmits a cross that is edited after being submitted, and tells
    # the user to remember to submit again (`Submission::user_updated`).
    was_submitted = submission.is_finalized
    commands: List[Any] = []
    if was_submitted:
        commands.append(UnFinalizeSubmission(creator=creator, client=client))
    # `command` is validated against the state the unfinalize leaves behind;
    # validating against the submitted state would reject every edit.
    validate_against = prospective_submission(submission, commands)
    commands.append(command)

    if not validate_command(form, command, validate_against, 'category'):
        raise BadRequest(response_data)

    try:
        submission, _ = current_app.api.save(*commands,
                                             submission_id=submission_id)
    except InvalidEvent as e:
        logger.debug('Could not change categories on %s: %s', submission_id, e)
        alerts.flash_failure(e.message)
        raise BadRequest(response_data) from e
    except SaveError as e:
        logger.error('Could not save cross-list category change')
        raise InternalServerError(response_data) from e

    if was_submitted:
        alerts.flash_warning(
            "Submission has been unsubmitted because of your update. Please"
            " remember to re-submit.")

    # Re-render from the saved state with a fresh form for the next change.
    return (_response_data(submission, submission_id, _add_form(submission)),
            status.OK, {})


def _submit_cross(form: SubmitCrossForm, submission: Submission,
                  submission_id: str, creator, client,
                  response_data: Dict[str, Any]) -> Response:
    """Finalize the cross-list, sending it to the announcement queue."""
    command = FinalizeCrossSubmission(creator=creator, client=client)
    if not validate_command(form, command, submission, 'category'):
        alerts.flash_failure(Markup(
            "There was a problem with your request. Please try again."
            f" {SUPPORT}"))
        raise BadRequest(response_data)

    try:
        current_app.api.save(command, submission_id=submission_id)
    except InvalidEvent as e:
        logger.debug('Could not submit cross %s: %s', submission_id, e)
        alerts.flash_failure(e.message)
        raise BadRequest(response_data) from e
    except SaveError as e:
        logger.error('Could not save cross-list submission')
        alerts.flash_failure(Markup(
            "There was a problem processing your request. Please try again."
            f" {SUPPORT}"))
        raise InternalServerError(response_data) from e

    alerts.flash_success("Cross list submitted.")
    return {}, status.SEE_OTHER, {
        'Location': url_for('ui.manage_submissions')}
