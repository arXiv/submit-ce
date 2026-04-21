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
)
from wtforms import SelectField
from wtforms.validators import DataRequired

from submit_ce.domain import Client, User, Event
from submit_ce.domain.event import SetUploadPackage, UpdateUploadPackage
from submit_ce.domain.submission import SubmissionContent, Submission
from submit_ce.domain.uploads import Workspace, FileStatus, UploadStatus
from submit_ce.domain.exceptions import SaveError
from submit_ce.ui.controllers.util import add_immediate_alert, validate_command
from submit_ce.ui.routes.flow_control import stay_on_this_stage
from submit_ce.ui.backend import get_submission
from submit_ce.ui import SUPPORT

from submit_ce.domain.compilation import Compilation

logger = logging.getLogger(__name__)

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103


class ReviewForm(csrf.CSRFForm):
    """Form for reviewing files and selecting compilation options."""
    
    # These choices will be populated dynamically in the controller
    source_file = SelectField('Select main source file', validators=[DataRequired()])
    compiler = SelectField('Select compiler', validators=[DataRequired()])
    compiler_version = SelectField('Select compiler version', validators=[DataRequired()])


def review_files(method: str, params: MultiDict, session: Session,
                 submission_id: str, **kwargs) -> Response:
    """Controller function to handle a file review request.

    GET requests are treated as a request for information about the current
    state of the submission for review.

    POST requests are treated as a request to update compilation settings
    or other review-related metadata.

    Parameters
    ----------
    method : str
        ``GET`` or ``POST``
    params : :class:`MultiDict`
        The form data from the request.
    session : :class:`Session`
        The authenticated session for the request.
    submission_id : str
        The identifier of the submission for which the review is being made.

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
    
    submission, _ = get_submission(submission_id)
    rdata.update({'submission_id': submission_id,
                  'submission': submission})

    if method not in ['GET', 'POST']:
        raise MethodNotAllowed()
    elif method == 'GET':
        return _get_review_data(params, session, submission, rdata)
    elif method == 'POST':
        form = ReviewForm(params)
        rdata.update({'form': form})
        
        # Populate dynamic choices before validation
        if submission.source_content:
            workspace = current_app.api.get_file_store().get_workspace(submission_id=submission.submission_id)
            if workspace and workspace.files:
                # Filter for TeX files and populate source_file choices
                tex_files = [(f.path, f.path) for f in workspace.files if f.path.endswith(('.tex', '.ltx'))]
                form.source_file.choices = tex_files

            # Populate compiler and version choices (dummy data for now)
            compilers = [(Compilation.SupportedCompiler.PDFLATEX.value, 'pdfLaTeX')]
            compiler_versions = [(Compilation.CompilerVersion.TEXLIVE_2025.value, 'TeX Live 2025')]
            
            form.compiler.choices = compilers
            form.compiler_version.choices = compiler_versions

        if not form.validate():
            alerts.flash_failure("There were problems with your selections. Please check the form.",
                                 title="Validation Error")
            return stay_on_this_stage((rdata, status.OK, {}))

        # TODO: Process form data (e.g., update submission with selected compiler, version, main file)
        alerts.flash_success("Review settings updated successfully!", title="Success")
        return stay_on_this_stage((rdata, status.OK, {}))


def _get_review_data(params: MultiDict, session: Session, submission: Submission,
                rdata: Dict[str, Any]) -> Response:
    """
    Get the current state of the submission and populate the review form.

    Parameters
    ----------
    params : :class:`MultiDict`
        The query parameters from the request.
    session : :class:`Session`
        The authenticated session for the request.
    submission : :class:`Submission`
        The submission for which to retrieve review information.

    Returns
    -------
    dict
        Response data, to render in template.
    int
        HTTP status code.
    dict
        Extra headers to add/update on the response.

    """
    form = ReviewForm()
    rdata.update({'status': None, 'form': form})

    if submission.source_content is None:
        # No files uploaded yet, so no review data to show
        return rdata, status.OK, {}

    upload_id = submission.source_content.identifier
    workspace = current_app.api.get_file_store().get_workspace(submission_id=submission.submission_id)
    rdata.update({'status': workspace})

    if workspace and workspace.files:
        # Filter for TeX files and populate source_file choices
        tex_files = [(f.path, f.path) for f in workspace.files if f.path.endswith(('.tex', '.ltx'))]
        form.source_file.choices = tex_files
        # Pre-select a default if available
        if tex_files:
            form.source_file.data = tex_files[0][0]

    # Populate compiler and version choices (dummy data for now)
    compilers = [(Compilation.SupportedCompiler.PDFLATEX.value, 'pdfLaTeX')]
    compiler_versions = [(Compilation.CompilerVersion.TEXLIVE_2025.value, 'TeX Live 2025')]
    
    form.compiler.choices = compilers
    form.compiler_version.choices = compiler_versions
    
    # Pre-select defaults
    form.compiler.data = Compilation.SupportedCompiler.PDFLATEX.value
    form.compiler_version.data = Compilation.CompilerVersion.TEXLIVE_2025.value


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
                    ' be able to able to process your files.'
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
