"""
Controllers for upload-related requests.

Things that still need to be done:

- Display error alerts from the file management service.
- Show warnings/errors for individual files in the table. We may need to
  extend the flashing mechanism to "flash" data to the next page (without
  displaying it as a notification to the user).

"""
import logging
import traceback
from collections import OrderedDict
from http import HTTPStatus as status
from locale import strxfrm
from pathlib import Path
from typing import Tuple, Dict, Any, Optional, List, Union

from arxiv.auth.domain import Session
from arxiv.base import alerts
from arxiv.forms import csrf
from markupsafe import Markup
from werkzeug.datastructures import FileStorage
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import (
    InternalServerError,
    MethodNotAllowed,
    RequestEntityTooLarge
)
from wtforms import BooleanField, FileField

from submit_ce.api.domain import Client, User, Event
from submit_ce.api.domain.event import SetUploadPackage, UpdateUploadPackage
from submit_ce.api.domain.submission import SubmissionContent, Submission
from submit_ce.api.domain.uploads import Upload, FileStatus, UploadStatus
from submit_ce.api.exceptions import SaveError
from submit_ce.ui.auth import user_and_client_from_session
from submit_ce.ui.backend import api
from submit_ce.ui.controllers.util import add_immediate_alert, validate_command
from submit_ce.ui.routes.flow_control import stay_on_this_stage
from submit_ce.ui.backend import get_submission

logger = logging.getLogger(__name__)

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103

PLEASE_CONTACT_SUPPORT = Markup(
    'If you continue to experience problems, please contact'
    ' <a href="mailto:help@arxiv.org"> arXiv support</a>.'
)


def tidy_filesize(size: int) -> str:
    """
    Convert upload size to human readable form.

    Decision to use powers of 10 rather than powers of 2 to stay compatible
    with Jinja filesizeformat filter with binary=false setting that we are
    using in file_upload template.

    Parameter: size in bytes
    Returns: formatted string of size in units up through GB

    """
    units = ["B", "KB", "MB", "GB"]
    if size == 0:
        return "0B"
    if size > 1000000000:
        return '{} {}'.format(size, units[3])
    units_index = 0
    while size > 1000:
        units_index += 1
        size = round(size / 1000, 3)
    return '{} {}'.format(size, units[units_index])


class UploadForm(csrf.CSRFForm):
    """Form for uploading files."""

    file = FileField('Choose a file...')
    ancillary = BooleanField('Ancillary')


def upload_files(method: str, params: MultiDict, session: Session,
                 submission_id: int, files: Optional[MultiDict] = None,
                 token: Optional[str] = None, **kwargs) -> Response:
    """Controller function to handle a file upload request.

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
                  'ui-app': submission,
                  'form': UploadForm()})

    if method not in ['GET', 'POST']:
        raise MethodNotAllowed()
    elif method == 'GET':
        return _get_upload(params, session, submission, rdata, token)
    elif method == 'POST':
        if not files or 'file' not in files or not files['file']:
            logger.debug('No files on request')
            if params.get('action', None):  # Don't flash a message if trying to go back to previous page
                return {}, status.SEE_OTHER, {}
            else:
                return stay_on_this_stage(_get_upload(params, session, submission, rdata, token))

        pointer = files['file']
        try:
            if submission.source_content is None:
                return _new_upload(params, pointer, session, submission, rdata, token)
            else:
                return _new_file(params, pointer, session, submission, rdata, token)
        except RequestEntityTooLarge as ex:
            logger.warning('POSTed upload was too large', ex)
            alerts.flash_failure(Markup('There was a problem uploading your file because it exceeds '
                                        'our maximum size limit. ' + PLEASE_CONTACT_SUPPORT))
        except Exception:
            logger.exception('Problem POSTing upload')
            alerts.flash_failure(Markup('There was a problem uploading your file. ' + PLEASE_CONTACT_SUPPORT))

        return stay_on_this_stage(_get_upload(params, session, submission, rdata, token))


def _update_submission(form: UploadForm, submission: Submission, stat: Upload,
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
        submission, _ = api.save(command, submission_id=submission.submission_id)
    except SaveError:
        alerts.flash_failure(Markup('There was a problem carrying out your request. Please try'
                    f' again. {PLEASE_CONTACT_SUPPORT}'))
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
        return rdata, status.OK, {}  # Nothing to show; generate a blank-slate upload page

    upload_id = submission.source_content.identifier
    status_data = alerts.get_hidden_alerts('_status')
    if type(status_data) is dict and status_data['identifier'] == upload_id:
        workspace = Upload.from_dict(status_data)
    else:
        workspace = api.get_file_store().get_workspace(submission_id=submission.submission_id,
                                                       upload_id=submission.source_content.identifier)
    rdata.update({'status': workspace})
    if workspace:
        rdata.update({'immediate_notifications': _get_notifications(workspace)})
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
        Extra headers to add/update on the response. Should include the `Location` header for use in a 303 redirect.

    """

    logger.debug('New upload package')
    submitter, client = user_and_client_from_session(session)
    params['file'] = pointer
    form = UploadForm(params)
    rdata.update({'form': form})

    if not form.validate():
        logger.debug('Invalid form data')
        return stay_on_this_stage((rdata, status.OK, {}))

    stat = api.upload(form.data['file'], submission.submission_id, submitter, client)
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
    logger.debug('Adding additional files')
    submitter, client = user_and_client_from_session(session)
    upload_id = submission.source_content.identifier

    # Using a form object provides some extra assurance that this is a legit request; provides CSRF protection.
    params['file'] = pointer
    form = UploadForm(params)
    rdata.update({'form': form, 'ui-app': submission})

    if not form.validate():
        logger.error('Invalid upload form: %s', form.errors)
        alerts.flash_failure("No file was uploaded; please try again.",
            title="Something went wrong")
        return stay_on_this_stage((rdata, status.OK, {}))
    #try:
    stat = api.get_file_store().add_file(upload_id, pointer, token,
                                         ancillary=form.ancillary.data)
    # except  as ex:
    #     try:
    #         ex_data = ex.response.json()
    #     except Exception:
    #         ex_data = None
    #     if ex_data is not None and 'reason' in ex_data:
    #         alerts.flash_failure(Markup(
    #             'There was a problem carrying out your request:'
    #             f' {ex_data["reason"]}. {PLEASE_CONTACT_SUPPORT}'
    #         ))
    #         return stay_on_this_stage((rdata, status.OK, {}))
    #     alerts.flash_failure(Markup(
    #         'There was a problem carrying out your request. Please try'
    #         f' again. {PLEASE_CONTACT_SUPPORT}'
    #     ))
    #     logger.debug('Failed to add file: %s', )
    #     logger.error(traceback.format_exc())
    #     raise InternalServerError(rdata) from ex

    submission = _update_submission(form, submission, stat, submitter, client)
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
