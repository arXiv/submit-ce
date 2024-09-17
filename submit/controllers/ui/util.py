"""Helpers for controllers."""

from typing import Callable, Any, Dict, Tuple, Optional, List, Union
from http import HTTPStatus as status

from arxiv_auth.domain import Session
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError, NotFound, BadRequest
from flask import url_for, Markup

from wtforms.widgets import ListWidget, CheckboxInput, Select, \
    html_params
from wtforms import StringField, PasswordField, SelectField, \
    SelectMultipleField, Form, validators, Field
from wtforms.fields.core import UnboundField

from arxiv.forms import csrf
from http import HTTPStatus as status
from arxiv import taxonomy
from arxiv.submission import InvalidEvent, User, Client, Event, Submission


Response = Tuple[Dict[str, Any], int, Dict[str, Any]]   # pylint: disable=C0103


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
        return Markup(''.join(html))


class OptGroupSelectField(SelectField):
    """A select field with optgroups."""

    widget = OptGroupSelectWidget()

    def pre_validate(self, form: Form) -> None:
        """Don't forget to validate also values from embedded lists."""
        for group_label, items in self.choices:
            for value, label in items:
                if value == self.data:
                    return
        raise ValueError(self.gettext('Not a valid choice'))

    def _value(self) -> str:
        data: str = self.data
        return data


class OptGroupSelectMultipleField(SelectMultipleField):
    """A multiple select field with optgroups."""

    widget = OptGroupSelectWidget(multiple=True)

    # def pre_validate(self, form: Form) -> None:
    #     """Don't forget to validate also values from embedded lists."""
    #     for group_label, items in self.choices:
    #         for value, label in items:
    #             if value == self.data:
    #                 return
    #     raise ValueError(self.gettext('Not a valid choice'))

    def _value(self) -> List[str]:
        data: List[str] = self.data
        return data


def validate_command(form: Form, event: Event,
                     submission: Optional[Submission] = None,
                     field: str = 'events',
                     message: Optional[str] = None) -> bool:
    """
    Validate an uncommitted command and apply the result to form validation.

    Parameters
    ----------
    form : :class:`.Form`
    command : :class:`.Event`
        Command/event to validate.
    submission : :class:`.Submission`
        The ui-app to which the command applies.
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
        event.validate(submission)
    except InvalidEvent as e:
        form.errors
        # This use of _errors causes a problem in WTForms 2.3.3
        # This fix might be of interest: https://github.com/wtforms/wtforms/pull/584
        if field not in form._errors:
            form._errors[field] = []
        if message is None:
            message = e.message
        form._errors[field].append(message)

        if hasattr(form, field):
            field_obj = getattr(form, field)
            if not field_obj.errors:
                field_obj.errors = []
            field_obj.errors.append(message)
        return False
    return True


class FieldMixin:
    """Provide a convenience classmethod for field names."""

    @classmethod
    def fields(cls):
        """Convenience accessor for form field names."""
        return [key for key in dir(cls)
                if isinstance(getattr(cls, key), UnboundField)]


# TODO: currently this does nothing with the client. We will need to add that
# bit once we have a plan for handling client information in this interface.
def user_and_client_from_session(session: Session) \
        -> Tuple[User, Optional[Client]]:
    """
    Get ui-app user/client representations from a :class:`.Session`.

    When we're building ui-app-related events, we frequently need a
    ui-app-friendly representation of the user or client responsible for
    those events. This function generates those event-domain representations
    from a :class:`arxiv_auth.domain.Submission` object.
    """
    user = User(
        session.user.user_id,
        email=session.user.email,
        forename=getattr(session.user.name, 'forename', None),
        surname=getattr(session.user.name, 'surname', None),
        suffix=getattr(session.user.name, 'suffix', None),
        endorsements=session.authorizations.endorsements
    )
    return user, None


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
