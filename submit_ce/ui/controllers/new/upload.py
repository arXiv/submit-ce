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

from submit_ce.domain import Client, Event, User
from submit_ce.domain.event import SetSourceFormat
from submit_ce.domain.event.file import UploadArchive, UploadFiles
from submit_ce.domain.submission import Submission
from submit_ce.domain.uploads import SourceFormat
from submit_ce.domain.uploads import Workspace, FileStatus, UploadStatus, is_file_tgz, is_file_zip
from submit_ce.domain import size_limits

from submit_ce.ui.filters import iec_filesize
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
    """Return True if the uploaded file is a tar.gz or zip archive."""
    pointer = files.get('file')
    if pointer is None:
        return False
    return is_file_tgz(pointer) or is_file_zip(pointer)


def _infer_source_format(files: List["FileStatus"]) -> Optional[SourceFormat]:
    """Infer source_format from workspace files.

    If any .tex file is present, the submission is TEX (legacy arXiv permits
    .pdf files, e.g. figures, inside a TeX submission, including in
    subdirectories). If the workspace is a single lone .pdf, the submission
    is PDF. Any other non-empty file set falls back to TEX, matching the
    legacy default for multi-file submissions. Returns None for an empty
    workspace.
    """
    if not files:
        return None
    if any(f.name.lower().endswith('.tex') for f in files):
        return SourceFormat.TEX
    if len(files) == 1 and files[0].name.lower().endswith('.pdf'):
        return SourceFormat.PDF
    return SourceFormat.TEX


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

    submission, events = get_submission(submission_id)
    rdata.update({'submission_id': submission_id,
                  'submission': submission,
                  'form': AddfilesForm()})

    if method not in ['GET', 'POST']:
        raise MethodNotAllowed()
    elif method == 'GET':
        return _get_upload(params, session, submission, events, rdata, token)
    elif method == 'POST':
        file_list = files.getlist('file') if files else []
        if len(file_list) > 1:
            raise BadRequest(description="Multi file upload not yet supported. Use a zip or tgz file.")

        file = file_list[0] if file_list else None
        params['file'] = file
        form = AddfilesForm(params)
        rdata.update({'form': form, 'submission': submission})
        if not form.validate():
            # Fix the format-string mismatch (was 3 %s placeholders with 2
            # args, which fired a noisy "--- Logging error ---" traceback
            # from Python's logging module and obscured the real error).
            logger.error(
                'Submission %s invalid upload form: %s',
                submission.submission_id, form.errors,
            )
            # CSRF expiry is a common cause when the page has been open
            # for a while. Surface that case explicitly so the user knows
            # to refresh the page rather than just clicking Upload again
            # with the same (still expired) token.
            errors = form.errors or {}
            if 'csrf_token' in errors:
                alerts.flash_failure(
                    "Your session token has expired. Please refresh "
                    "this page and try the upload again."
                )
            else:
                alerts.flash_failure("No file was uploaded; please try again.")
            return stay_on_this_stage((rdata, status.OK, {}))

        is_archive = "ARCHIVE" if (is_file_tgz(file) or is_file_zip(file)) else "NONARCHIVE"
        try:
            match (file, params.get('action'), is_archive):
                case (_, 'next', _):
                    if submission.source_format is None:
                        alerts.flash_warning(
                            "Cannot proceed: please upload a single PDF, or"
                            " one or more .tex files.",
                            title='Source format required')
                        return stay_on_this_stage(_get_upload((rdata, status.OK, {}, token)))
                    return ready_for_next((rdata, status.OK, {}))
                case (_, action, _) if action:  # trying to go back to previous page
                    return {}, status.SEE_OTHER, {}
                case (None, _, _):
                    logger.debug('No files on request')
                    return stay_on_this_stage(_get_upload(params, session, submission, events, rdata, token))
                case (_, _, "ARCHIVE"):
                    return _upload_archive(form, file, submitter, client, submission, rdata, token)
                case (_, _, "NONARCHIVE"):
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

        return stay_on_this_stage(_get_upload(params, session, submission, events, rdata, token))



def _get_upload(params: MultiDict, session: Session, submission: Submission,
                events: List[Event],
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

    if not conditions.has_files(submission, events):
        return rdata, status.OK, {}  # Nothing to show; generate a blank-slate upload page

    status_data = alerts.get_hidden_alerts('_status')
    if type(status_data) is dict and status_data['identifier'] == submission.submission_id:
        workspace = Workspace.model_validate(status_data)
    else:
        workspace = current_app.api.get_file_store().get_workspace(submission_id=str(submission.submission_id))

    rdata.update({'status': workspace})
    if workspace:
        rdata.update({'immediate_notifications': _get_notifications(submission, workspace)})
    return rdata, status.OK, {}


def _flash_oversize_warning(submission: Submission) -> None:
    """Warn the submitter that an oversize submission will be held for review.

    The submission is not rejected: the size check is a soft gate. The flag is
    persisted during event save; the auto-hold is applied when the submission is
    finalized."""
    if not submission.is_oversize:
        return
    alerts.flash_warning(
        Markup(f'This submission exceeds the {iec_filesize(size_limits.DEFAULT_MAX_SIZE_BYTES)} arXiv '
               'size guideline.'
               'Please consider reducing the size of the files to ensure your paper can be accessed by readers. '
               'If the size of the files are necessary to present the work then please continue with '
               'the submission steps and click the "Process" button. '
               'For more information, please read about <a href="/help/sizes">Oversized Submissions</a>.'),
        title='Submission is oversize')


def _upload_archive(form: AddfilesForm, file: FileStorage,
                    submitter: User, client: Client,
                    submission: Submission, rdata: Dict[str, Any], token: str) \
        -> Response:
    """Handle a POST request with a archive like a tgz or a zip."""
    command = UploadArchive(creator=submitter, client=client, file=file)
    validate_command(form, command, submission, 'file')  # raises on invalid
    submission, _ = current_app.api.save(command, submission_id=submission.submission_id)
    workspace = current_app.api.get_file_store().get_workspace(submission_id=str(submission.submission_id))
    converted_size = iec_filesize(workspace.size)

    inferred = _infer_source_format(workspace.files)
    if submission.source_format != inferred:
        target = inferred.value if inferred is not None else None
        submission, _ = current_app.api.save(
            SetSourceFormat(creator=submitter, client=client, source_format=target),
            submission_id=submission.submission_id,
        )
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
    _flash_oversize_warning(submission)
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
    converted_size = iec_filesize(workspace.size)

    inferred = _infer_source_format(workspace.files)
    if submission.source_format != inferred:
        target = inferred.value if inferred is not None else None
        submission, _ = current_app.api.save(
            SetSourceFormat(creator=submitter, client=client, source_format=target),
            submission_id=submission.submission_id,
        )

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
    _flash_oversize_warning(submission)
    alerts.flash_hidden(workspace.model_dump(), '_status')

    rdata.update({'status': workspace})
    return stay_on_this_stage((rdata, status.OK, {}))


def _get_notifications(submission: Submission, workspace: Workspace) -> List[Dict[str, str]]:
    notifications = []
    if not workspace.files:   # Nothing in the upload workspace.
        return notifications
    if workspace.status is UploadStatus.ERRORS:
        notifications.append({
            'title': 'Unresolved errors',
            'severity': 'danger',
            'body': 'There are unresolved problems with your submission'
                    ' files. Please correct the errors below before'
                    ' proceeding.'
        })
    elif workspace.status is UploadStatus.READY_WITH_WARNINGS:
        notifications.append({
            'title': 'Warnings',
            'severity': 'warning',
            'body': 'There is one or more unresolved warning in the file list.'
                    ' You may proceed with your submission, but please note'
                    ' that these issues may cause delays in processing'
                    ' and/or announcement.'
        })
    has_tex = any(f.name.lower().endswith('.tex') for f in workspace.files)
    if has_tex:
        notifications.append({
            'title': 'Detected TEX',
            'severity': 'success',
            'body': 'Your submission content is supported.'
        })
    elif submission.source_format == SourceFormat.PDF:
        notifications.append({
            'title': 'Detected PDF',
            'severity': 'success',
            'body': 'Your submission content is supported.'
        })
    elif submission.source_format == SourceFormat.INVALID:
        notifications.append({
            'title': 'Unsupported submission type',
            'severity': 'danger',
            'body': 'It is likely that your submission content is not'
                    ' supported. Please check your files carefully. We may not'
                    ' be able to process your files.'
        })
    else:
        notifications.append({
            'title': 'Unknown submission type',
            'severity': 'warning',
            'body': 'We could not determine the source type of your'
                    ' submission. Please check your files carefully. We may'
                    ' not be able to process your files.'
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
