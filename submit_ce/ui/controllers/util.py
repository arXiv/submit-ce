"""Helpers for controllers."""

import copy
from typing import Any, Callable, Dict, Iterable, List, Tuple, Optional, Union

from flask import current_app
from markupsafe import Markup
from wtforms.validators import StopValidation
from wtforms.widgets import Select, html_params
from wtforms import SelectField, Form
from wtforms.fields.core import UnboundField

from arxiv.taxonomy.category import Category
from arxiv.taxonomy.definitions import ARCHIVES_ACTIVE, CATEGORIES_ACTIVE

from submit_ce.domain import Event, Submission
from submit_ce.domain.exceptions import InvalidEvent, NoSuchDocument
from submit_ce.domain.submission import SubmissionType

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]   # pylint: disable=C0103

Choices = List[Tuple[str, List[Tuple[str, str]]]]
"""Nested ``(group, [(value, label), ...])`` shape :class:`.OptGroupSelectField`
renders and validates against."""


class OptGroupSelectWidget(Select):
    """Select widget with optgroups."""

    def __call__(self, field: SelectField, **kwargs: Any) -> Markup:
        """Render the `select` element with `optgroup`s."""
        kwargs.setdefault('id', field.id)
        if self.multiple:
            kwargs['multiple'] = True
        html = [f'<select {html_params(name=field.name, **kwargs)}>']
        html.append('<option></option>')
        for group_label, items in field.choices:
            html.append('<optgroup %s>' % html_params(label=group_label))
            for value, label in items:
                option = self.render_option(value, label, value == field.data)
                html.append(option)
            html.append('</optgroup>')
        html.append('</select>')
        return Markup(''.join(html)) # TODO this was changed to Markup, was that correct?


class OptGroupSelectField(SelectField):
    """A select field with optgroups."""

    widget = OptGroupSelectWidget()

    def pre_validate(self, form: Form) -> None:
        """Don't forget to validate also values from embedded lists."""
        for group_label, items in self.choices:
            for value, label in items:
                if value == self.data:
                    return
        raise StopValidation(self.gettext('Not a valid choice'))

    def _value(self) -> str:
        data: str = self.data
        return data


def category_choices(label: Callable[[str, Category], str]) -> Choices:
    """Active categories grouped by active archive.

    ``label`` builds the display string from the category id and the category, so
    each form keeps its own wording.
    """
    return [
        (archive.id, [
            (category_id, label(category_id, category))
            for category_id, category in CATEGORIES_ACTIVE.items()
            if category.in_archive == archive_id
        ])
        for archive_id, archive in ARCHIVES_ACTIVE.items()
    ]


def prune_choices(choices: Choices, keep: Callable[[str], bool]) -> Choices:
    """The choices ``keep`` accepts, without the groups that leaves empty.

    ``keep`` sees the category id. An archive with nothing left to offer is
    dropped rather than rendered as an empty ``optgroup``.
    """
    pruned = [
        (group, [(value, label) for value, label in items if keep(value)])
        for group, items in choices
    ]
    return [(group, items) for group, items in pruned if items]


def validate_command(form: Form, event: Event,
                     submission: Optional[Submission] = None,
                     field: str = 'events',
                     message: Optional[str] = None) -> bool:
    """Validate an uncommitted command and if there are any errors, put them on
    the correct fields in the form.

    Parameters
    ----------
    form : :class:`.Form`
    command : :class:`.Event`
        Command/event to validate.
    submission : :class:`.Submission`
        The submission to which the command applies.
    field : str
        Name of the field on the form to update with error messages if
        validation fails. Default is `events`, accessible at
        ``form.errors['events']``.
    message : str or None
        If provided, the error message to add to the form. If ``None``
        (default) the :class:`.InvalidEvent` message will be used.

    Returns
    -------
    bool
    """
    try:
        event.validate_pre_lock(submission)
        return True
    except InvalidEvent as e:
        # This use of _errors causes a problem in WTForms 2.3.3
        # This fix might be of interest: https://github.com/wtforms/wtforms/pull/584
        if hasattr(form, field):
            field_obj = getattr(form, field)
            if not field_obj.errors:
                field_obj.errors = []
            field_obj.errors.append(message or e.message)
        return False


def validate_commands(form: Form, events: Iterable[Event],
                     submission: Optional[Submission] = None,
                     field: str = 'events',
                     message: Optional[str] = None) -> bool:
    """Validate an uncommitted command and if there are any errors, put them on
    the correct fields in the form.

    Parameters
    ----------
    form : :class:`.Form`
    commands : `Iterable[Event]`
        Commands/events to validate.
    submission : :class:`.Submission`
        The submission to which the command applies.
    field : str
        Name of the field on the form to update with error messages if
        validation fails. Default is `events`, accessible at
        ``form.errors['events']``.
    message : str or None
        If provided, the error message to add to the form. If ``None``
        (default) the :class:`.InvalidEvent` message will be used.

    Returns
    -------
    bool if all commands validate.
    """
    return all([validate_command(form, event, submission, field, message) for event in events])


class FieldMixin:
    """Provide a convenience classmethod for field names."""

    @classmethod
    def fields(cls):
        """Convenience accessor for form field names."""
        return [key for key in dir(cls)
                if isinstance(getattr(cls, key), UnboundField)]


def prospective_submission(submission: Submission,
                           commands: Iterable[Event]) -> Submission:
    """The submission as ``commands`` would leave it, for pre-validation.

    Some commands are only valid against the state an earlier command in the
    same save is about to produce -- finalizing a jref needs the citation data
    the pending ``Set*`` events supply; editing a submitted cross-list needs it
    unfinalized first. Validating those against the submission as it stands
    would reject every one.

    ``project`` rather than ``apply``: it is the pure field update, so this
    neither re-runs validation nor leaves ``_before``/``_after`` on the command
    objects that :meth:`save` is about to apply for real. The deep copy keeps the
    state the real save starts from untouched.
    """
    prospective = copy.deepcopy(submission)
    for command in commands:
        prospective = command.project(prospective)
    return prospective


def active_submission_id(paper_id: str,
                         submission_type: Optional[SubmissionType] = None) \
        -> Optional[str]:
    """Id of the paper's in-progress submission, if it has one.

    A paper gets one active submission at a time, so this answers both of the
    questions the paper-keyed create controllers ask. Pass ``submission_type`` to
    count only submissions of that type -- an in-progress journal reference (or
    cross-list) is one to resume, where an in-progress anything-else is one that
    blocks. With no type, any in-progress submission counts.

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


def add_immediate_alert(context: dict, severity: str,
                        message: Union[str, dict], title: Optional[str] = None,
                        dismissable: bool = True, safe: bool = False) -> None:
    """Add an alert for immediate display."""
    if safe and isinstance(message, str):
        message = Markup(message)
    data = {'message': message, 'title': title, 'dismissable': dismissable}

    if 'immediate_alerts' not in context:
        context['immediate_alerts'] = []
    context['immediate_alerts'].append((severity, data))
