"""
Controllers for file-delete-related requests.
"""

from http import HTTPStatus as status
from typing import Tuple, Dict, Any, Optional
import logging

from arxiv.forms import csrf
from flask import current_app

from submit_ce.domain.event import SetSourceFormat
from submit_ce.domain.event.file import RemoveAllFiles, RemoveFiles
from submit_ce.ui.auth import user_and_client_from_session
from submit_ce.ui.controllers.new.upload import _infer_source_format
from arxiv.auth.domain import Session
from werkzeug.datastructures import MultiDict
from wtforms import BooleanField, HiddenField
from wtforms.validators import DataRequired
from submit_ce.ui.backend import get_submission
from submit_ce.ui.routes.flow_control import stay_on_this_stage, return_to_parent_stage
from submit_ce.ui.controllers.util import validate_command


#from arxiv.submission.services import Filemanager


logger = logging.getLogger(__name__)

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103


def delete_all(method: str, params: MultiDict, session: Session,
               submission_id: str, token: Optional[str] = None,
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
    submission_id : str
        The identifier of the submission for which the deletion is being made.
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
    submission, _ = get_submission(submission_id)
    # TODO need to check the submitter and client?
    submitter, client = user_and_client_from_session(session)
    rdata = {'submission': submission, 'submission_id': submission_id}

    if method == 'GET':
        rdata.update({'form': DeleteAllFilesForm()})
        return stay_on_this_stage((rdata, status.OK, {}))
    elif method == 'POST':
        form = DeleteAllFilesForm(params)
        rdata.update({'form': form})
        if not (form.validate() and form.confirmed.data):
            return stay_on_this_stage((rdata, status.OK, {}))

        command = RemoveAllFiles(creator=submitter, client=client)
        if validate_command(form, command, submission, 'add_files'):
            submission, _ = current_app.api.save(command, submission_id=submission.submission_id)
            if submission.source_format is not None:
                current_app.api.save(
                    SetSourceFormat(creator=submitter, client=client, source_format=None),
                    submission_id=submission.submission_id,
                )
            return return_to_parent_stage((rdata, status.OK, {}))

    return return_to_parent_stage((rdata, status.BAD_REQUEST, {}))



def delete_file(method: str, params: MultiDict, session: Session,
                submission_id: str, token: Optional[str] = None,
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
    submission_id : str
        The identifier of the submission for which the deletion is being made.
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
    submission, _ = get_submission(submission_id)
    submitter, client = user_and_client_from_session(session)
    rdata = {'submission': submission, 'submission_id': submission_id}

    if method == 'GET':
        # The only thing that we want to get from the request params on a GET
        # request is the file path. This way there is no way for a GET request
        # to trigger actual deletion. The user must explicitly indicate via
        # a valid POST that the file should in fact be deleted.
        params = MultiDict({'file_path': params['path']})
        rdata.update({'form': DeleteFileForm(params)})
        return stay_on_this_stage((rdata, status.OK, {}))
    elif method == 'POST':
        form = DeleteFileForm(params)
        rdata.update({'form': form})
        if not (form.validate() and form.confirmed.data and form.file_path.data):
            return stay_on_this_stage((rdata, status.OK, {}))

        command = RemoveFiles(creator=submitter, client=client, files=[form.file_path.data])
        if validate_command(form, command, submission, 'add_files'):
            submission, _ = current_app.api.save(command, submission_id=submission.submission_id)
            workspace = current_app.api.get_file_store().get_workspace(
                submission_id=str(submission.submission_id))
            if workspace is not None:
                inferred = _infer_source_format(workspace.files)
                if submission.source_format != inferred:
                    target = inferred.value if inferred is not None else None
                    current_app.api.save(
                        SetSourceFormat(creator=submitter, client=client, source_format=target),
                        submission_id=submission.submission_id,
                    )
            return return_to_parent_stage((rdata, status.OK, {}))

    return return_to_parent_stage((rdata, status.BAD_REQUEST, {}))




def _files_under(workspace, prefix: str) -> list[str]:
    """Paths of every stored file under directory ``prefix`` (normalized to end
    with '/'). A file belongs to the directory when its path starts with the
    prefix (SUBMISSION-229)."""
    p = prefix if prefix.endswith('/') else prefix + '/'
    files = workspace.files if workspace is not None else []
    return [f.path for f in files if f.path.startswith(p)]


def delete_dir(method: str, params: MultiDict, session: Session,
               submission_id: str, token: Optional[str] = None,
               **kwargs) -> Response:
    """Delete every file under a directory (SUBMISSION-229).

    Directory-scoped counterpart of :func:`delete_file`: reuses the locked
    ``RemoveFiles`` event with the full list of files under the directory
    prefix. Like ``delete_file``, deletion only happens on a POST carrying
    ``confirmed``; a GET only reads the ``prefix`` query param and renders the
    confirmation form, so a GET can never delete.
    """
    submission, _ = get_submission(submission_id)
    submitter, client = user_and_client_from_session(session)
    rdata = {'submission': submission, 'submission_id': submission_id}
    workspace = current_app.api.get_file_store().get_workspace(
        submission_id=str(submission_id))

    if method == 'GET':
        # Only read the directory prefix from the GET; never delete on GET.
        prefix = params['prefix']
        rdata.update({'form': DeleteDirForm(MultiDict({'dir_prefix': prefix})),
                      'dir_prefix': prefix,
                      'dir_files': _files_under(workspace, prefix)})
        return stay_on_this_stage((rdata, status.OK, {}))
    elif method == 'POST':
        form = DeleteDirForm(params)
        rdata.update({'form': form})
        if not (form.validate() and form.confirmed.data and form.dir_prefix.data):
            return stay_on_this_stage((rdata, status.OK, {}))

        targets = _files_under(workspace, form.dir_prefix.data)
        if not targets:
            # Nothing under the prefix (already gone / bad prefix): no-op.
            return return_to_parent_stage((rdata, status.OK, {}))

        command = RemoveFiles(creator=submitter, client=client, files=targets)
        if validate_command(form, command, submission, 'add_files'):
            submission, _ = current_app.api.save(command, submission_id=submission.submission_id)
            workspace = current_app.api.get_file_store().get_workspace(
                submission_id=str(submission.submission_id))
            if workspace is not None:
                inferred = _infer_source_format(workspace.files)
                if submission.source_format != inferred:
                    target = inferred.value if inferred is not None else None
                    current_app.api.save(
                        SetSourceFormat(creator=submitter, client=client, source_format=target),
                        submission_id=submission.submission_id,
                    )
            return return_to_parent_stage((rdata, status.OK, {}))

    return return_to_parent_stage((rdata, status.BAD_REQUEST, {}))


class DeleteFileForm(csrf.CSRFForm):
    """Form for deleting individual files."""

    file_path = HiddenField('File', validators=[DataRequired()])
    confirmed = BooleanField('Confirmed', validators=[DataRequired()])


class DeleteDirForm(csrf.CSRFForm):
    """Form for deleting all files under a directory (SUBMISSION-229)."""

    dir_prefix = HiddenField('Directory', validators=[DataRequired()])
    confirmed = BooleanField('Confirmed', validators=[DataRequired()])


class DeleteAllFilesForm(csrf.CSRFForm):
    """Form for deleting all files in the workspace."""

    confirmed = BooleanField('Confirmed', validators=[DataRequired()])
