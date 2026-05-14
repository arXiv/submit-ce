"""
Controllers for upload-related requests.

Things that still need to be done:

- Display error alerts from the file management service.
- Show warnings/errors for individual files in the table. We may need to
  extend the flashing mechanism to "flash" data to the next page (without
  displaying it as a notification to the user).

"""

import logging
from collections import OrderedDict
from http import HTTPStatus as status
from locale import strxfrm
from pathlib import Path
from typing import Tuple, Dict, Any, Optional, List, Union, assert_never

from fastapi.exceptions import HTTPException
from flask import current_app
from arxiv.auth.domain import Session
from arxiv.base import alerts
from arxiv.base.filters import tidy_filesize
from arxiv.forms import csrf
from markupsafe import Markup
from werkzeug.datastructures import FileStorage
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import (
    BadRequest,
    MethodNotAllowed,
    RequestEntityTooLarge
)
from wtforms import BooleanField, FileField

from submit_ce.domain import Client, User, Event
from submit_ce.domain.event.file import UploadArchive, UploadFiles
from submit_ce.domain.submission import Submission
from submit_ce.domain.uploads import SourceFormat
from submit_ce.domain.uploads import Workspace, FileStatus, UploadStatus, is_file_tgz
from submit_ce.domain.exceptions import SaveError

from submit_ce.ui.auth import user_and_client_from_session
from submit_ce.ui.controllers.util import add_immediate_alert, validate_command
from submit_ce.ui.routes.flow_control import ready_for_next, stay_on_this_stage
from submit_ce.ui.backend import get_submission
from submit_ce.ui import SUPPORT
from submit_ce.ui.workflow import conditions


logger = logging.getLogger(__name__)


Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103


CHUNK_SIZE = 1024 * 4



_TARGZ_MIMETYPES = frozenset({
    'application/gzip',
    'application/x-gzip',
    'application/x-tar',
    'application/tar+gzip',
    'application/x-compressed',
})


def _single_file_archive(files: MultiDict) -> bool:
    """Return True if the uploaded file is a tar.gz archive."""
    pointer = files.get('file')
    if pointer is None:
        return False
    return is_file_tgz(pointer)


class AddfilesForm(csrf.CSRFForm):
    """Form for uploading files."""

    file = FileField('Choose a file...')
    # TODO ancillary field is not yet handled by controller
    ancillary = BooleanField('Ancillary')


def upload_files(method: str, params: MultiDict, session: Session,
                 submission_id: str, files: Optional[MultiDict] = None,
                 token: Optional[str] = None, **kwargs) -> Response:
    """Controller function to handle a file upload request.

    GET requests are treated as a request for information about the current
    state of the submission upload.

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
    submission_id : str
        The identifier of the submission for which the upload is being made.
    token : str
        The original (encrypted) auth token on the request. Used to perform
        sub-requests to the file management service.

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
    submitter, client = user_and_client_from_session(session)

    rdata = {}
    if files is None or token is None:
        add_immediate_alert(rdata, alerts.FAILURE, 'Missing auth files or token')
        return stay_on_this_stage((rdata, status.OK, {}))

    submission, _ = get_submission(submission_id)
    rdata.update({'submission_id': submission_id,
                  'submission': submission,
                  'form': AddfilesForm()})

    if method not in ['GET', 'POST']:
        raise MethodNotAllowed()
    elif method == 'GET':
        return _get_upload(params, session, submission, rdata, token)
    elif method == 'POST':
        file_list = files.getlist('file') if files else []
        if len(file_list) > 1:
            raise BadRequest(description="Multi file upload not yet supported. Use a zip or tgz file.")

        file = file_list[0] if file_list else None
        params['file'] = file_list[0]
        form = AddfilesForm(params)
        rdata.update({'form': form, 'submission': submission})
        if not form.validate():
            logger.error('Submission %s Invalid upload form: %s %s', submission.submission_id, form.errors)
            alerts.flash_failure("No file was uploaded; please try again.")
            return stay_on_this_stage((rdata, status.OK, {}))

        is_archive = "ARCHIVE" if is_file_tgz(file) else "NONARCHIVE"
        # TODO not sure if has_files is useful any more. _upload_files can upload with or without files,
        has_files = submission.uncompressed_size > 0
        try:
            match (file, params.get('action'), has_files, is_archive):
                case (_, 'next', _, _):
                    return ready_for_next((rdata, status.OK, {}))
                case (_, action, _, _) if action:  # trying to go back to previous page
                    return {}, status.SEE_OTHER, {}
                case (None, _,  _, _):
                    logger.debug('No files on request')
                    return stay_on_this_stage(_get_upload(params, session, submission, rdata, token))
                case (_, _, False, "ARCHIVE"):
                    return _upload_archive(form, file, submitter, client, submission, rdata, token)
                case (_, _, True, "ARCHIVE"):
                    raise BadRequest(description="Archive upload with existing files not yet supported.")
                case (_, _, _, "NONARCHIVE"):
                    return _upload_files(form, file, submitter, client, submission, rdata, token)
                case unhandled:
                    assert_never(unhandled)
        except RequestEntityTooLarge as ex:
            logger.warning('POSTed upload was too large', ex)
            alerts.flash_failure(Markup('There was a problem uploading your file because it exceeds '
                                        'our maximum size limit. ' + SUPPORT))
        except HTTPException as ex:
            alerts.flash_failure(Markup(ex.detail))
        except Exception:
            logger.exception('Problem POSTing upload')
            alerts.flash_failure(Markup('There was a problem uploading your file. ' + SUPPORT))

        return stay_on_this_stage(_get_upload(params, session, submission, rdata, token))



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
        The submission for which to retrieve upload workspace information.

    Returns
    -------
    dict
        Response data, to render in template.
    int
        HTTP status code.
    dict
        Extra headers to add/update on the response.

    """
    rdata.update({'status': None, 'form': AddfilesForm()})

    if not conditions.has_files(submission):
        return rdata, status.OK, {}  # Nothing to show; generate a blank-slate upload page

    status_data = alerts.get_hidden_alerts('_status')
    if type(status_data) is dict and status_data['identifier'] == submission.submission_id:
        workspace = Workspace.model_validate(status_data)
    else:
        workspace = current_app.api.get_file_store().get_workspace(submission_id=str(submission.submission_id))

    rdata.update({'status': workspace})
    if workspace:
        rdata.update({'immediate_notifications': _get_notifications(workspace)})
    return rdata, status.OK, {}



def _upload_archive(form: AddfilesForm, file: FileStorage,
                    submitter: User, client: Client,
                    submission: Submission, rdata: Dict[str, Any], token: str) \
        -> Response:
    """Handle a POST request with a archive like a tgz or a zip."""
    command = UploadArchive(creator=submitter, client=client, file=file)
    validate_command(form, command, submission, 'file')  # raises on invalid
    submission, _ = current_app.api.save(command, submission_id=submission.submission_id)
    workspace = current_app.api.get_file_store().get_workspace(submission_id=str(submission.submission_id))
    converted_size = tidy_filesize(workspace.size)
    if workspace.status is UploadStatus.READY:
        alerts.flash_success(
            f'Unpacked {workspace.file_count} files. Total submission'
            f' package size is {converted_size}',
            title='Upload successful'
        )
    elif workspace.status is UploadStatus.READY_WITH_WARNINGS:
        alerts.flash_warning(
            f'Unpacked {workspace.file_count} files. Total submission'
            f' package size is {converted_size}. See below for warnings.',
            title='Upload complete, with warnings'
        )
    elif workspace.status is UploadStatus.ERRORS:
        alerts.flash_warning(
            f'Unpacked {workspace.file_count} files. Total submission'
            f' package size is {converted_size}. See below for errors.',
            title='Upload complete, with errors'
        )
    alerts.flash_hidden(workspace.model_dump(), '_status')

    rdata.update({'status': workspace})
    return stay_on_this_stage((rdata, status.OK, {}))


def _upload_files(form: AddfilesForm, file: FileStorage,
                 submitter: User, client: Client,
                 submission: Submission, rdata: Dict[str, Any], token: str)\
        -> Response:
    """Handle a POST with a files to add to a submission."""
    command = UploadFiles(creator=submitter, client=client, files=[file])
    validate_command(form, command, submission, 'file')
    submission, _ = current_app.api.save(command, submission_id=submission.submission_id)
    workspace = current_app.api.get_file_store().get_workspace(submission_id=str(submission.submission_id))
    converted_size = tidy_filesize(workspace.size)
    if workspace.status is UploadStatus.READY:
        alerts.flash_success(
            f'Uploaded file. Total submission'
            f' package size is {converted_size}',
            title='Upload successful'
        )
    elif workspace.status is UploadStatus.READY_WITH_WARNINGS:
        alerts.flash_warning(
            f'Uploaded file. Total submission'
            f' package size is {converted_size}. See below for warnings.',
            title='Upload complete, with warnings'
        )
    elif workspace.status is UploadStatus.ERRORS:
        alerts.flash_warning(
            f'Uploaded file. Total submission'
            f' package size is {converted_size}. See below for errors.',
            title='Upload complete, with errors'
        )
    alerts.flash_hidden(workspace.model_dump(), '_status')

    rdata.update({'status': workspace})
    return stay_on_this_stage((rdata, status.OK, {}))


def _get_notifications(stat: Workspace) -> List[Dict[str, str]]:
    notifications = []
    if not stat.files:   # Nothing in the upload workspace.
        return notifications
    if stat.status is UploadStatus.ERRORS:
        notifications.append({
            'title': 'Unresolved errors',
            'severity': 'danger',
            'body': 'There are unresolved problems with your submission'
                    ' files. Please correct the errors below before'
                    ' proceeding.'
        })
    elif stat.status is UploadStatus.READY_WITH_WARNINGS:
        notifications.append({
            'title': 'Warnings',
            'severity': 'warning',
            'body': 'There is one or more unresolved warning in the file list.'
                    ' You may proceed with your submission, but please note'
                    ' that these issues may cause delays in processing'
                    ' and/or announcement.'
        })
    if stat.source_format is SourceFormat.UNKNOWN:
        notifications.append({
            'title': 'Unknown submission type',
            'severity': 'warning',
            'body': 'We could not determine the source type of your'
                    ' submission. Please check your files carefully. We may'
                    ' not be able to process your files.'
        })
    elif stat.source_format is SourceFormat.INVALID:
        notifications.append({
            'title': 'Unsupported submission type',
            'severity': 'danger',
            'body': 'It is likely that your submission content is not'
                    ' supported. Please check your files carefully. We may not'
                    ' be able to process your files.'
        })
    else:
        notifications.append({
            'title': f'Detected {stat.source_format.value.upper()}',
            'severity': 'success',
            'body': 'Your submission content is supported.'
        })
    return notifications


def group_files(files: List[FileStatus]) -> OrderedDict:
    """Group a set of file status objects by directory structure.

    Parameters
    ----------
    files
        Elements are :class:`FileStatus` objects.

    Returns
    -------
    :class:`OrderedDict` Keys are strings of either file or directory names.  Values are either :class:`FileStatus`
    instances (leaves) or :class:`OrderedDict` (containing more :class:`FileStatus` and/or :class:`OrderedDict`).
    """
    tree = {}
    # First step is to organize the list into a directory tree.
    for file in files:
        path = Path(file.path)
        level = tree
        for p in reversed(path.parents):
            if str(p) == '.':
                continue
            if p.name in level and isinstance(level[p.name], dict):
                level = level[p.name]
            else:
                new_level = {}
                level[p.name] = new_level
                level = new_level
        level[path.name] = file

    # Reorder for nice display, sorted files first, then sorted directories. Recursive.
    def _order(node: Union[dict, FileStatus]) -> OrderedDict:
        # split subtree into FileStatus and other
        filestats = [fs for key, fs in node.items()
                     if type(fs) is FileStatus]
        deeper_subtrees = [(key, st) for key, st in node.items()
                           if type(st) is not FileStatus]

        # add the sorted files at this level before any subtrees
        ordered_subtree = OrderedDict()
        for fs in sorted(filestats, key=lambda fs: strxfrm(fs.path.casefold())):
            ordered_subtree[fs.path] = fs
        # subtrees go after the files
        for key, deeper in sorted(deeper_subtrees, key=lambda tup: strxfrm(tup[0].casefold())):
            ordered_subtree[key] = _order(deeper)

        return ordered_subtree

    return _order(tree)
