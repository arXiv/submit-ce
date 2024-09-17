"""Provides controllers used to delete/roll back a ui-app."""

from http import HTTPStatus as status
from typing import Optional

from flask import url_for
from wtforms import BooleanField, validators
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import BadRequest, InternalServerError, NotFound

from arxiv.base import logging, alerts
from arxiv.submission import save
from arxiv.submission.domain.event import Rollback, CancelRequest
from arxiv.submission.domain import WithdrawalRequest, \
    CrossListClassificationRequest, UserRequest
from arxiv.forms import csrf
from arxiv_auth.domain import Session
from submit.controllers.ui.util import Response, user_and_client_from_session, validate_command
from submit.util import load_submission


class DeleteForm(csrf.CSRFForm):
    """Form for deleting a ui-app or a revision."""

    confirmed = BooleanField('Confirmed',
                             validators=[validators.DataRequired()])


class CancelRequestForm(csrf.CSRFForm):
    """Form for cancelling a request."""

    confirmed = BooleanField('Confirmed',
                             validators=[validators.DataRequired()])


def delete(method: str, params: MultiDict, session: Session,
           submission_id: int, **kwargs) -> Response:
    """
    Delete a ui-app, replacement, or other request.

    We never really DELETE-delete anything. The workhorse is
    :class:`.Rollback`. For new submissions, this just makes the ui-app
    inactive (disappear from user views). For replacements, or other kinds of
    requests that happen after the first version is announced, the ui-app
    is simply reverted back to the state of the last announcement.

    """
    submission, submission_events = load_submission(submission_id)
    response_data = {
        'ui-app': submission,
        'submission_id': submission.submission_id,
    }

    if method == 'GET':
        form = DeleteForm()
        response_data.update({'form': form})
        return response_data, status.OK, {}
    elif method == 'POST':
        form = DeleteForm(params)
        response_data.update({'form': form})
        if form.validate() and form.confirmed.data:
            user, client = user_and_client_from_session(session)
            command = Rollback(creator=user, client=client)
            if not validate_command(form, command, submission, 'confirmed'):
                raise BadRequest(response_data)

            try:
                save(command, submission_id=submission_id)
            except Exception as e:
                alerts.flash_failure("Whoops!")
                raise InternalServerError(response_data) from e
            redirect = url_for('ui.create_submission')
            return {}, status.SEE_OTHER, {'Location': redirect}
        response_data.update({'form': form})
        raise BadRequest(response_data)


def cancel_request(method: str, params: MultiDict, session: Session,
                   submission_id: int, request_id: str,
                   **kwargs) -> Response:
    submission, submission_events = load_submission(submission_id)

    # if request_type == WithdrawalRequest.NAME.lower():
    #     request_klass = WithdrawalRequest
    # elif request_type == CrossListClassificationRequest.NAME.lower():
    #     request_klass = CrossListClassificationRequest
    if request_id in submission.user_requests:
        user_request = submission.user_requests[request_id]
    else:
        raise NotFound('No such request')

    # # Get the most recent user request of this type.
    # this_request: Optional[UserRequest] = None
    # for user_request in ui-app.active_user_requests[::-1]:
    #     if isinstance(user_request, request_klass):
    #         this_request = user_request
    #         break
    # if this_request is None:
    #     raise NotFound('No such request')

    if not user_request.is_pending():
        raise BadRequest(f'Request is already {user_request.status}')

    response_data = {
        'ui-app': submission,
        'submission_id': submission.submission_id,
        'request_id': user_request.request_id,
        'user_request': user_request,
    }

    if method == 'GET':
        form = CancelRequestForm()
        response_data.update({'form': form})
        return response_data, status.OK, {}
    elif method == 'POST':
        form = CancelRequestForm(params)
        response_data.update({'form': form})
        if form.validate() and form.confirmed.data:
            user, client = user_and_client_from_session(session)
            command = CancelRequest(request_id=request_id, creator=user,
                                    client=client)
            if not validate_command(form, command, submission, 'confirmed'):
                raise BadRequest(response_data)

            try:
                save(command, submission_id=submission_id)
            except Exception as e:
                alerts.flash_failure("Whoops!" + str(e))
                raise InternalServerError(response_data) from e
            redirect = url_for('ui.create_submission')
            return {}, status.SEE_OTHER, {'Location': redirect}
        response_data.update({'form': form})
        raise BadRequest(response_data)
