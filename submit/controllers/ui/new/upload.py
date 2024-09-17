"""
Controllers for upload-related requests.

Things that still need to be done:

- Display error alerts from the file management service.
- Show warnings/errors for individual files in the table. We may need to
  extend the flashing mechanism to "flash" data to the next page (without
  displaying it as a notification to the user).

"""

import traceback
from collections import OrderedDict
from http import HTTPStatus as status
from locale import strxfrm
from typing import Tuple, Dict, Any, Optional, List, Union, Mapping

from flask import url_for, Markup
from werkzeug.datastructures import MultiDict
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import (
    InternalServerError,
    BadRequest,
    MethodNotAllowed,
    RequestEntityTooLarge
)
from wtforms import BooleanField, HiddenField, FileField
from wtforms.validators import DataRequired

from arxiv.base import logging, alerts
from arxiv.forms import csrf
from arxiv.integration.api import exceptions
from arxiv.submission import save, Submission, User, Client, Event
from arxiv.submission.services import Filemanager
from arxiv.submission.domain.uploads import Upload, FileStatus, UploadStatus
from arxiv.submission.domain.submission import SubmissionContent
from arxiv.submission.domain.event import SetUploadPackage, UpdateUploadPackage
from arxiv.submission.exceptions import SaveError
from arxiv_auth.domain import Session

from submit.controllers.ui.util import (
    validate_command,
    user_and_client_from_session
)
from submit.util import load_submission, tidy_filesize
from submit.routes.ui.flow_control import ready_for_next, stay_on_this_stage
from submit.controllers.ui.util import add_immediate_alert

logger = logging.getLogger(__name__)

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103

PLEASE_CONTACT_SUPPORT = Markup(
    'If you continue to experience problems, please contact'
    ' <a href="mailto:help@arxiv.org"> arXiv support</a>.'
)


def upload_files(method: str, params: MultiDict, session: Session,
                 submission_id: int, files: Optional[MultiDict] = None,
                 token: Optional[str] = None, **kwargs) -> Response:
    """Handle a file upload request.

    GET requests are treated as a request for information about the current
    state of the ui-app upload.

    POST requests are treated either as package upload if the upload
    workspace does not already exist or a request to replace a file.

    Parameters
    ----------
    method : str
        ``GET`` or ``POST``
    params : :class:`MultiDict`
        The form data from the request.
    files : :class:`MultiDict`
        File data in the multipart request. Values should be
        :class:`FileStorage` instances.
    session : :class:`Session`
        The authenticated session for the request.
    submission_id : int
        The identifier of the ui-app for which the upload is being made.
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
    if files is None or token is None:
        add_immediate_alert(rdata, alerts.FAILURE,
                            'Missing auth files or token')
        return stay_on_this_stage((rdata, status.OK, {}))

    submission, _ = load_submission(submission_id)

    rdata.update({'submission_id': submission_id,
                  'ui-app': submission,
                  'form': UploadForm()})

    if method not in ['GET', 'POST']:
        raise MethodNotAllowed()
    elif method == 'GET':
        logger.debug('GET; load current upload state')
        return _get_upload(params, session, submission, rdata, token)
    elif method == 'POST':
        try:    # Make sure that we have a file to work with.
            pointer = files['file']
        except KeyError:   # User is going back, saving/exiting, or next step.
            pointer = None

        if not pointer:
            # Don't flash a message if the user is just trying to go back to the
            # previous page.
            logger.debug('No files on request')
            action = params.get('action', None)
            if action:
                logger.debug('User is navigating away from upload UI')
                return {}, status.SEE_OTHER, {}
            else:
                return stay_on_this_stage(_get_upload(params, session,
                                                      submission, rdata, token))

        try:
            if submission.source_content is None:
                logger.debug('New upload package')
                return _new_upload(params, pointer, session, submission, rdata, token)
            else:
                logger.debug('Adding additional files')
                return _new_file(params, pointer, session, submission, rdata, token)
        except exceptions.ConnectionFailed as ex:
            logger.debug('Problem POSTing upload: %s', ex)
            alerts.flash_failure(Markup(
                'There was a problem uploading your file. '
                f'{PLEASE_CONTACT_SUPPORT}'))
        except RequestEntityTooLarge as ex:
            logger.debug('Problem POSTing upload: %s', ex)
            alerts.flash_failure(Markup(
                'There was a problem uploading your file because it exceeds '
                f'our maximum size limit. {PLEASE_CONTACT_SUPPORT}'))
        return stay_on_this_stage(_get_upload(params, session, submission, rdata, token))


class UploadForm(csrf.CSRFForm):
    """Form for uploading files."""

    file = FileField('Choose a file...')
    ancillary = BooleanField('Ancillary')


def _update(form: UploadForm, submission: Submission, stat: Upload,
            submitter: User, client: Optional[Client] = None) \
        -> Optional[Submission]:
    """
    Update the :class:`.Submission` after an upload-related action.

    The ui-app is linked to the upload workspace via the
    :attr:`Submission.source_content` attribute. This is set using a
    :class:`SetUploadPackage` command. If the workspace identifier changes
    (e.g. on first upload), we want to execute :class:`SetUploadPackage` to
    make the association.

    Parameters
    ----------
    form : WTForm for adding validation error messages
    submission : :class:`Submission`
    stat : :class:`Upload`
    submitter : :class:`User`
    client : :class:`Client` or None

    """
    existing_upload = getattr(submission.source_content, 'identifier', None)

    command: Event
    if existing_upload == stat.identifier:
        command = UpdateUploadPackage(creator=submitter, client=client,
                                      checksum=stat.checksum,
                                      uncompressed_size=stat.size,
                                      compressed_size=stat.compressed_size,
                                      source_format=stat.source_format)
    else:
        command = SetUploadPackage(creator=submitter, client=client,
                                   identifier=stat.identifier,
                                   checksum=stat.checksum,
                                   compressed_size=stat.compressed_size,
                                   uncompressed_size=stat.size,
                                   source_format=stat.source_format)

    if not validate_command(form, command, submission):
        return None

    try:
        submission, _ = save(command, submission_id=submission.submission_id)
    except SaveError:
        alerts.flash_failure(Markup(
            'There was a problem carrying out your request. Please try'
            f' again. {PLEASE_CONTACT_SUPPORT}'
        ))
    return submission


def _get_upload(params: MultiDict, session: Session, submission: Submission,
                rdata: Dict[str, Any], token) -> Response:
    """
    Get the current state of the upload workspace, and prepare a response.

    Parameters
    ----------
    params : :class:`MultiDict`
        The query parameters from the request.
    session : :class:`Session`
        The authenticated session for the request.
    submission : :class:`Submission`
        The ui-app for which to retrieve upload workspace information.

    Returns
    -------
    dict
        Response data, to render in template.
    int
        HTTP status code.
    dict
        Extra headers to add/update on the response.

    """
    rdata.update({'status': None, 'form': UploadForm()})

    if submission.source_content is None:
        # Nothing to show; should generate a blank-slate upload screen.
        return rdata, status.OK, {}

    fm = Filemanager.current_session()

    upload_id = submission.source_content.identifier
    status_data = alerts.get_hidden_alerts('_status')
    if type(status_data) is dict and status_data['identifier'] == upload_id:
        stat = Upload.from_dict(status_data)
    else:
        try:
            stat = fm.get_upload_status(upload_id, token)
        except exceptions.RequestFailed as ex:
            # TODO: handle specific failure cases.
            logger.debug('Failed to get upload status: %s', ex)
            logger.error(traceback.format_exc())
            raise InternalServerError(rdata) from ex
    rdata.update({'status': stat})
    if stat:
        rdata.update({'immediate_notifications': _get_notifications(stat)})
    return rdata, status.OK, {}


def _new_upload(params: MultiDict, pointer: FileStorage, session: Session,
                submission: Submission, rdata: Dict[str, Any], token: str) \
        -> Response:
    """
    Handle a POST request with a new upload package.

    This occurs in the case that there is not already an upload workspace
    associated with the ui-app. See the :attr:`Submission.source_content`
    attribute, which is set using :class:`SetUploadPackage`.

    Parameters
    ----------
    params : :class:`MultiDict`
        The form data from the request.
    pointer : :class:`FileStorage`
        The file upload stream.
    session : :class:`Session`
        The authenticated session for the request.
    submission : :class:`Submission`
        The ui-app for which the upload is being made.

    Returns
    -------
    dict
        Response data, to render in template.
    int
        HTTP status code. This should be ``303``, unless something goes wrong.
    dict
        Extra headers to add/update on the response. This should include
        the `Location` header for use in the 303 redirect response.

    """
    submitter, client = user_and_client_from_session(session)
    fm = Filemanager.current_session()

    params['file'] = pointer
    form = UploadForm(params)
    rdata.update({'form': form})

    if not form.validate():
        logger.debug('Invalid form data')
        return stay_on_this_stage((rdata, status.OK, {}))

    try:
        stat = fm.upload_package(pointer, token)
    except exceptions.RequestFailed as ex:
        alerts.flash_failure(Markup(
            'There was a problem carrying out your request. Please try'
            f' again. {PLEASE_CONTACT_SUPPORT}'
        ))
        logger.debug('Failed to upload package: %s', ex)
        logger.error(traceback.format_exc())
        raise InternalServerError(rdata) from ex

    submission = _update(form, submission, stat, submitter, client)
    converted_size = tidy_filesize(stat.size)
    if stat.status is UploadStatus.READY:
        alerts.flash_success(
            f'Unpacked {stat.file_count} files. Total ui-app'
            f' package size is {converted_size}',
            title='Upload successful'
        )
    elif stat.status is UploadStatus.READY_WITH_WARNINGS:
        alerts.flash_warning(
            f'Unpacked {stat.file_count} files. Total ui-app'
            f' package size is {converted_size}. See below for warnings.',
            title='Upload complete, with warnings'
        )
    elif stat.status is UploadStatus.ERRORS:
        alerts.flash_warning(
            f'Unpacked {stat.file_count} files. Total ui-app'
            f' package size is {converted_size}. See below for errors.',
            title='Upload complete, with errors'
        )
    alerts.flash_hidden(stat.to_dict(), '_status')

    rdata.update({'status': stat})
    return stay_on_this_stage((rdata, status.OK, {}))

#    loc = url_for('ui.file_upload', submission_id=ui-app.submission_id)
#    return {}, status.SEE_OTHER, {'Location': loc}


def _new_file(params: MultiDict, pointer: FileStorage, session: Session,
              submission: Submission, rdata: Dict[str, Any], token: str) \
        -> Response:
    """
    Handle a POST request with a new file to add to an existing upload package.

    This occurs in the case that there is already an upload workspace
    associated with the ui-app. See the :attr:`Submission.source_content`
    attribute, which is set using :class:`SetUploadPackage`.

    Parameters
    ----------
    params : :class:`MultiDict`
        The form data from the request.
    pointer : :class:`FileStorage`
        The file upload stream.
    session : :class:`Session`
        The authenticated session for the request.
    submission : :class:`Submission`
        The ui-app for which the upload is being made.

    Returns
    -------
    dict
        Response data, to render in template.
    int
        HTTP status code. This should be ``303``, unless something goes wrong.
    dict
        Extra headers to add/update on the response. This should include
        the `Location` header for use in the 303 redirect response.

    """
    submitter, client = user_and_client_from_session(session)
    fm = Filemanager.current_session()
    upload_id = submission.source_content.identifier

    # Using a form object provides some extra assurance that this is a legit
    # request; provides CSRF goodies.
    params['file'] = pointer
    form = UploadForm(params)
    rdata.update({'form': form, 'ui-app': submission})

    if not form.validate():
        logger.error('Invalid upload form: %s', form.errors)
        alerts.flash_failure(
            "No file was uploaded; please try again.",
            title="Something went wrong")
        return stay_on_this_stage((rdata, status.OK, {}))

    ancillary: bool = form.ancillary.data

    try:
        stat = fm.add_file(upload_id, pointer, token, ancillary=ancillary)
    except exceptions.RequestFailed as ex:
        try:
            ex_data = ex.response.json()
        except Exception:
            ex_data = None
        if ex_data is not None and 'reason' in ex_data:
            alerts.flash_failure(Markup(
                'There was a problem carrying out your request:'
                f' {ex_data["reason"]}. {PLEASE_CONTACT_SUPPORT}'
            ))
            return stay_on_this_stage((rdata, status.OK, {}))
        alerts.flash_failure(Markup(
            'There was a problem carrying out your request. Please try'
            f' again. {PLEASE_CONTACT_SUPPORT}'
        ))
        logger.debug('Failed to add file: %s', )
        logger.error(traceback.format_exc())
        raise InternalServerError(rdata) from ex

    submission = _update(form, submission, stat, submitter, client)
    converted_size = tidy_filesize(stat.size)
    if stat.status is UploadStatus.READY:
        alerts.flash_success(
            f'Uploaded {pointer.filename} successfully. Total ui-app'
            f' package size is {converted_size}',
            title='Upload successful'
        )
    elif stat.status is UploadStatus.READY_WITH_WARNINGS:
        alerts.flash_warning(
            f'Uploaded {pointer.filename} successfully. Total ui-app'
            f' package size is {converted_size}. See below for warnings.',
            title='Upload complete, with warnings'
        )
    elif stat.status is UploadStatus.ERRORS:
        alerts.flash_warning(
            f'Uploaded {pointer.filename} successfully. Total ui-app'
            f' package size is {converted_size}. See below for errors.',
            title='Upload complete, with errors'
        )
    status_data = stat.to_dict()
    alerts.flash_hidden(status_data, '_status')
    rdata.update({'status': stat})
    return stay_on_this_stage((rdata, status.OK, {}))


def _get_notifications(stat: Upload) -> List[Dict[str, str]]:
    # TODO: these need wordsmithing.
    notifications = []
    if not stat.files:   # Nothing in the upload workspace.
        return notifications
    if stat.status is UploadStatus.ERRORS:
        notifications.append({
            'title': 'Unresolved errors',
            'severity': 'danger',
            'body': 'There are unresolved problems with your ui-app'
                    ' files. Please correct the errors below before'
                    ' proceeding.'
        })
    elif stat.status is UploadStatus.READY_WITH_WARNINGS:
        notifications.append({
            'title': 'Warnings',
            'severity': 'warning',
            'body': 'There is one or more unresolved warning in the file list.'
                    ' You may proceed with your ui-app, but please note'
                    ' that these issues may cause delays in processing'
                    ' and/or announcement.'
        })
    if stat.source_format is SubmissionContent.Format.UNKNOWN:
        notifications.append({
            'title': 'Unknown ui-app type',
            'severity': 'warning',
            'body': 'We could not determine the source type of your'
                    ' ui-app. Please check your files carefully. We may'
                    ' not be able to process your files.'
        })
    elif stat.source_format is SubmissionContent.Format.INVALID:
        notifications.append({
            'title': 'Unsupported ui-app type',
            'severity': 'danger',
            'body': 'It is likely that your ui-app content is not'
                    ' supported. Please check your files carefully. We may not'
                    ' be able to process your files.'
        })
    else:
        notifications.append({
            'title': f'Detected {stat.source_format.value.upper()}',
            'severity': 'success',
            'body': 'Your ui-app content is supported.'
        })
    return notifications


def group_files(files: List[FileStatus]) -> OrderedDict:
    """Group a set of file status objects by directory structure.

    Parameters
    ----------
    list
        Elements are :class:`FileStatus` objects.

    Returns ------- :class:`OrderedDict` Keys are strings of either
    file or directory names.  Values are either :class:`FileStatus`
    instances (leaves) or :class:`OrderedDict` (containing more
    :class:`FileStatus` and/or :class:`OrderedDict`, etc).

    """
    # First step is to organize by file tree.
    tree = {}
    for f in files:
        parts = f.path.split('/')
        if len(parts) == 1:
            tree[f.name] = f
        else:
            subtree = tree
            for part in parts[:-1]:
                if part not in subtree:
                    subtree[part] = {}
                subtree = subtree[part]
            subtree[parts[-1]] = f

    # Reorder subtrees for nice display.
    def _order(node: Union[dict, FileStatus]) -> OrderedDict:
        if type(node) is FileStatus:
            return node

        in_subtree: dict = node

        # split subtree into FileStatus and other
        filestats = [fs for key, fs in in_subtree.items()
                     if type(fs) is FileStatus]
        deeper_subtrees = [(key, st) for key, st in in_subtree.items()
                           if type(st) is not FileStatus]

        # add the files at this level before any subtrees
        ordered_subtree = OrderedDict()
        if filestats and filestats is not None:
            for fs in sorted(filestats,
                             key=lambda fs: strxfrm(fs.path.casefold())):
                ordered_subtree[fs.path] = fs

        if deeper_subtrees:
            for key, deeper in sorted(deeper_subtrees,
                                      key=lambda tup: strxfrm(
                                          tup[0].casefold())):
                ordered_subtree[key] = _order(deeper)

        return ordered_subtree

    return _order(tree)
