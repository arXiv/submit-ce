"""
Controllers for file-delete-related requests.
"""

from http import HTTPStatus as status
from typing import Tuple, Dict, Any, Optional

from arxiv.base import logging, alerts
from arxiv.forms import csrf
from arxiv.integration.api import exceptions
from arxiv.submission import save
from arxiv.submission.domain.event import UpdateUploadPackage
from arxiv.submission.domain.uploads import Upload
from arxiv.submission.exceptions import SaveError
from arxiv.submission.services import Filemanager
from arxiv_auth.domain import Session
from flask import url_for, Markup
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import BadRequest, MethodNotAllowed
from wtforms import BooleanField, HiddenField
from wtforms.validators import DataRequired

from submit.controllers.ui.util import validate_command, \
    user_and_client_from_session
from submit.util import load_submission
from submit.routes.ui.flow_control import ready_for_next, \
    stay_on_this_stage, return_to_parent_stage
from submit.controllers.ui.util import add_immediate_alert

logger = logging.getLogger(__name__)

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103

PLEASE_CONTACT_SUPPORT = Markup(
    'If you continue to experience problems, please contact'
    ' <a href="mailto:help@arxiv.org"> arXiv support</a>.'
)


def delete_all(method: str, params: MultiDict, session: Session,
               submission_id: int, token: Optional[str] = None,
               **kwargs) -> Response:
    """
    Handle a request to delete all files in the workspace.

    Parameters
    ----------
    method : str
        ``GET`` or ``POST``
    params : :class:`MultiDict`
        The query or form data from the request.
    session : :class:`Session`
        The authenticated session for the request.
    submission_id : int
        The identifier of the ui-app for which the deletion is being made.
    token : str
        The original (encrypted) auth token on the request. Used to perform
        subrequests to the file management service.

    Returns
    -------
    dict
    int
        Response data, to render in template.
        HTTP status code. This should be ``200`` or ``303``, unless something
        goes wrong.
    dict
        Extra headers to add/update on the response. This should include
        the `Location` header for use in the 303 redirect response, if
        applicable.

    """
    rdata = {}
    if token is None:
        add_immediate_alert(rdata, alerts.FAILURE, 'Missing auth token')
        return stay_on_this_stage((rdata, status.OK, {}))

    fm = Filemanager.current_session()
    submission, submission_events = load_submission(submission_id)
    upload_id = submission.source_content.identifier
    submitter, client = user_and_client_from_session(session)
    rdata.update({'ui-app': submission, 'submission_id': submission_id})

    if method == 'GET':
        form = DeleteAllFilesForm()
        rdata.update({'form': form})
        return stay_on_this_stage((rdata, status.OK, {}))

    elif method == 'POST':
        form = DeleteAllFilesForm(params)
        rdata.update({'form': form})

        if not (form.validate() and form.confirmed.data):
            return stay_on_this_stage((rdata, status.OK, {}))

        try:
            stat = fm.delete_all(upload_id, token)
        except exceptions.RequestForbidden as e:
            alerts.flash_failure(Markup(
                'There was a problem authorizing your request. Please try'
                f' again. {PLEASE_CONTACT_SUPPORT}'
            ))
            logger.error('Encountered RequestForbidden: %s', e)
        except exceptions.BadRequest as e:
            alerts.flash_warning(Markup(
                'Something odd happened when processing your request.'
                f'{PLEASE_CONTACT_SUPPORT}'
            ))
            logger.error('Encountered BadRequest: %s', e)
        except exceptions.RequestFailed as e:
            alerts.flash_failure(Markup(
                'There was a problem carrying out your request. Please try'
                f' again. {PLEASE_CONTACT_SUPPORT}'
            ))
            logger.error('Encountered RequestFailed: %s', e)

        command = UpdateUploadPackage(creator=submitter, client=client,
                                      checksum=stat.checksum,
                                      uncompressed_size=stat.size,
                                      source_format=stat.source_format)
        if not validate_command(form, command, submission):
            logger.debug('Command validation failed')
            return return_to_parent_stage((rdata, status.OK, {}))

        try:
            submission, _ = save(command, submission_id=submission_id)
        except SaveError:
            alerts.flash_failure(Markup(
                'There was a problem carrying out your request. Please try'
                f' again. {PLEASE_CONTACT_SUPPORT}'
            ))

        return return_to_parent_stage((rdata, status.OK, {}))

    raise MethodNotAllowed('Method not supported')


def delete_file(method: str, params: MultiDict, session: Session,
                submission_id: int, token: Optional[str] = None,
                **kwargs) -> Response:
    """
    Handle a request to delete a file.

    The file will only be deleted if a POST request is made that also contains
    the ``confirmed`` parameter.

    The process can be initiated with a GET request that contains the
    ``path`` (key) for the file to be deleted. For example, a button on
    the upload interface may link to the deletion route with the file path
    as a query parameter. This will generate a deletion confirmation form,
    which can be POSTed to complete the action.

    Parameters
    ----------
    method : str
        ``GET`` or ``POST``
    params : :class:`MultiDict`
        The query or form data from the request.
    session : :class:`Session`
        The authenticated session for the request.
    submission_id : int
        The identifier of the ui-app for which the deletion is being made.
    token : str
        The original (encrypted) auth token on the request. Used to perform
        subrequests to the file management service.

    Returns
    -------
    dict
        Response data, to render in template.
    int
        HTTP status code. This should be ``200`` or ``303``, unless something
        goes wrong.
    dict
        Extra headers to add/update on the response. This should include
        the `Location` header for use in the 303 redirect response, if
        applicable.

    """
    rdata = {}
    if token is None:
        add_immediate_alert(rdata, alerts.FAILURE, 'Missing auth token')
        return stay_on_this_stage((rdata, status.OK, {}))

    fm = Filemanager.current_session()
    submission, submission_events = load_submission(submission_id)
    upload_id = submission.source_content.identifier
    submitter, client = user_and_client_from_session(session)

    rdata = {'ui-app': submission, 'submission_id': submission_id}

    if method == 'GET':
        # The only thing that we want to get from the request params on a GET
        # request is the file path. This way there is no way for a GET request
        # to trigger actual deletion. The user must explicitly indicate via
        # a valid POST that the file should in fact be deleted.
        params = MultiDict({'file_path': params['path']})

    form = DeleteFileForm(params)
    rdata.update({'form': form})

    if method == 'POST':
        if not (form.validate() and form.confirmed.data):
            logger.debug('Invalid form data')
            return stay_on_this_stage((rdata, status.OK, {}))

        stat: Optional[Upload] = None
        try:
            file_path = form.file_path.data
            stat = fm.delete_file(upload_id, file_path, token)
            alerts.flash_success(
                f'File <code>{form.file_path.data}</code> was deleted'
                ' successfully', title='Deleted file successfully',
                safe=True
            )
        except (exceptions.RequestForbidden, exceptions.BadRequest, exceptions.RequestFailed):
            alerts.flash_failure(Markup(
                'There was a problem carrying out your request. Please try'
                f' again. {PLEASE_CONTACT_SUPPORT}'
            ))

        if stat is not None:
            command = UpdateUploadPackage(creator=submitter,
                                          checksum=stat.checksum,
                                          uncompressed_size=stat.size,
                                          source_format=stat.source_format)
            if not validate_command(form, command, submission):
                logger.debug('Command validation failed')
                return stay_on_this_stage((rdata, status.OK, {}))
            try:
                submission, _ = save(command, submission_id=submission_id)
            except SaveError:
                alerts.flash_failure(Markup(
                    'There was a problem carrying out your request. Please try'
                    f' again. {PLEASE_CONTACT_SUPPORT}'
                ))
        return return_to_parent_stage(({}, status.OK, {}))
    return stay_on_this_stage((rdata, status.OK, {}))


class DeleteFileForm(csrf.CSRFForm):
    """Form for deleting individual files."""

    file_path = HiddenField('File', validators=[DataRequired()])
    confirmed = BooleanField('Confirmed', validators=[DataRequired()])


class DeleteAllFilesForm(csrf.CSRFForm):
    """Form for deleting all files in the workspace."""

    confirmed = BooleanField('Confirmed', validators=[DataRequired()])
