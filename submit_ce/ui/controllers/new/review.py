"""
Placeholder Controllers for review files requests. (COMING SOON)

I will be using this placeholder to assist in setting up preflight and
directives backend routines. After files are uploaded we call preflight,
generate directives file. Then we present the Review Files page using the
directives data.

"""

import logging
from collections import OrderedDict
from http import HTTPStatus as status
from locale import strxfrm
from pathlib import Path
from typing import Tuple, Dict, Any, Optional, List, Union

from flask import current_app
from arxiv.auth.domain import Session
from arxiv.base import alerts
from arxiv.forms import csrf
from markupsafe import Markup
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import (
    MethodNotAllowed,
    RequestEntityTooLarge
)
from wtforms import BooleanField, FileField

from submit_ce.domain import Client, User, Event
from submit_ce.domain.event import SetUploadPackage, UpdateUploadPackage
from submit_ce.domain.submission import SubmissionContent, Submission
from submit_ce.domain.uploads import Workspace, FileStatus, UploadStatus
from submit_ce.domain.exceptions import SaveError

from submit_ce.ui.controllers.util import add_immediate_alert, validate_command
from submit_ce.ui.routes.flow_control import stay_on_this_stage
from submit_ce.ui.backend import get_submission
from submit_ce.ui import SUPPORT


logger = logging.getLogger(__name__)

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103

class UploadForm(csrf.CSRFForm):
    """Form for uploading files."""

    file = FileField('Choose a file...')
    ancillary = BooleanField('Ancillary')


def review_files(method: str, params: MultiDict, session: Session,
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
    rdata = {}
    if files is None or token is None:
        add_immediate_alert(rdata, alerts.FAILURE, 'Missing auth files or token')
        return stay_on_this_stage((rdata, status.OK, {}))

    submission, _ = get_submission(submission_id)
    rdata.update({'submission_id': submission_id,
                  'submission': submission,
                  'form': UploadForm()})

    if method not in ['GET', 'POST']:
        raise MethodNotAllowed()
    elif method == 'GET':
        # We should not need to refresh preflight or regenerate directive file here.
        return _get_upload(params, session, submission, rdata, token)
    elif method == 'POST':
        if not files or 'file' not in files or not files['file']:
            logger.debug('No files on request')
            if params.get('action', None):  # Don't flash a message if trying to go back to previous page
                return {}, status.SEE_OTHER, {}
            else:
                return stay_on_this_stage(_get_upload(params, session, submission, rdata, token))

        try:
            # Add call to preflight and directives IN THIS AREA
            # The files have already been uploaded and installed during Add Files step.
            if submission.source_content is None:
                # is this possible?
                pass
            else:
                # Call preflight
                # Call directives
                pass
        except RequestEntityTooLarge as ex:
            logger.warning('POSTed upload was too large', ex)
            alerts.flash_failure(Markup('There was a problem uploading your file because it exceeds '
                                        'our maximum size limit. ' + SUPPORT))
        except Exception:
            logger.exception('Problem POSTing upload')
            alerts.flash_failure(Markup('There was a problem uploading your file. ' + SUPPORT))

        return stay_on_this_stage(_get_upload(params, session, submission, rdata, token))


def _update_submission(form: UploadForm, submission: Submission, stat: Workspace,
                       submitter: User, client: Optional[Client] = None) \
        -> Optional[Submission]:
    """
    Update the :class:`.Submission` after an upload-related action.

    The submission is linked to the upload workspace via the
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
        submission, _ = current_app.api.save(command, submission_id=submission.submission_id)
    except SaveError:
        alerts.flash_failure(Markup('There was a problem carrying out your request. Please try'
                    f' again. {SUPPORT}'))
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
    rdata.update({'status': None, 'form': UploadForm()})

    if submission.source_content is None:
        return rdata, status.OK, {}  # Nothing to show; generate a blank-slate upload page

    upload_id = submission.source_content.identifier
    status_data = alerts.get_hidden_alerts('_status')
    if type(status_data) is dict and status_data['identifier'] == upload_id:
        workspace = Workspace.from_dict(status_data)
    else:
        workspace = current_app.api.get_file_store().get_workspace(submission_id=submission.submission_id)
    rdata.update({'status': workspace})

    if workspace:
        rdata.update({'immediate_notifications': _get_notifications(workspace)})
    return rdata, status.OK, {}

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
    if stat.source_format is SubmissionContent.Format.UNKNOWN:
        notifications.append({
            'title': 'Unknown submission type',
            'severity': 'warning',
            'body': 'We could not determine the source type of your'
                    ' submission. Please check your files carefully. We may'
                    ' not be able to process your files.'
        })
    elif stat.source_format is SubmissionContent.Format.INVALID:
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
