import json
import logging
from collections import OrderedDict
from http import HTTPStatus as status
from locale import strxfrm
from pathlib import Path
from typing import Tuple, Dict, Any, Optional, List, Union

from flask import current_app
from arxiv.auth.domain import Session
from arxiv.base import alerts
from submit_ce.domain.event.process import StartPreflight, StartDirectives  # noqa: F401 (StartDirectives used below)
from ...auth import user_and_client_from_session
from arxiv.files import FileObj, FileDoesNotExist
from arxiv.forms import csrf
from markupsafe import Markup
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import (
    InternalServerError,
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
from submit_ce.ui.routes.flow_control import stay_on_this_stage, ready_for_next, return_to_parent_stage
from submit_ce.ui.backend import get_submission
from submit_ce.ui import SUPPORT

from submit_ce.domain.compilation import Compilation

from submit_ce.implementations.compile.directive_manager import DirectiveManager as dm 

logger = logging.getLogger(__name__)

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103

'''
The submit 1.5 workflow:
  src/00README.json -> gcp_preflight.json + form -> directives -> pdf + src/00README.json

The submit 2 workflow:
  If gcp_preflight.json does not exist then /preflight is called
  The src/00README.json is copied user_decisions.json, then deleted.
  user_decisions.json is loaded into the web form, and if changed,
    the new values will overwrite it.
  If any files are changed, or the user changes values in the form
  then gcp_preflight.json is deleted, and we restart with /preflight.
  When no more changes are made, /directives is called, and we move
    forward to the processing page.

Special cases for later:
  If the user goes back to add-files, and edits the src/00README,
    it's ignored,
    and the last edits save to user_decisions.json are reloaded.
  Could just delete user_decisions.json on leaving add-files

TODO:
- call workflow.validate
- fix test_integration.py
- incorporate preflight error messages into html file list, if any.
- in add-files, delete preflight if user modifies files.
- in add-files, delete user_decisions if user uploads src/zzrm
'''

class ReviewForm(csrf.CSRFForm):
    """Form for reviewing files and selecting compilation options."""
    
    # These choices will be populated dynamically in the controller
    source_file = SelectField('Select main source file', validators=[DataRequired()])
    compiler = SelectField('Select compiler', validators=[DataRequired()])
    compiler_version = SelectField('Select compiler version', validators=[DataRequired()])


def review_files(method: str, params: MultiDict, session: Session,
                 submission_id: str, token: str, **kwargs) -> Response:
    """Controller for the review-files workflow stage.

    On GET, ensures preflight data exists (running preflight if needed),
    seeds user_decisions from a 00README.json if present, and populates the
    form with detected source files and compiler choices.

    On POST, compares submitted form values against the stored user_decisions
    and the workspace files. If the user changed compiler options or marked
    files for deletion, the preflight is invalidated and the flow returns to
    the parent (add-files) stage. Otherwise directives are generated (if not
    already present) and the flow advances to the next stage.

    Parameters
    ----------
    method : str
        HTTP method for the request; only 'GET' and 'POST' are accepted.
    params : MultiDict
        Request parameters. On POST this carries the ReviewForm fields
        (``source_file``, ``compiler``, ``compiler_version``) and the
        ``selected_files`` list of paths the user marked for deletion.
    session : Session
        Authenticated arXiv session for the current user; used to derive
        submitter/client identities when dispatching StartPreflight and
        StartDirectives commands.
    submission_id : str
        Identifier of the submission being reviewed; used to look up the
        workspace, preflight, user_decisions, and directives blobs.
    token : str
        Auth token forwarded to downstream service calls (preflight,
        directives) triggered by this controller.
    **kwargs
        Unused; accepted for compatibility with the controller dispatch
        signature.

    Returns
    -------
    Response
        Tuple of ``(rdata, status_code, headers)`` where ``rdata`` contains
        the submission, workspace, form, and preflight-derived file notes
        used to render the review template. The tuple is wrapped by a
        flow-control helper (``stay_on_this_stage``, ``return_to_parent_stage``,
        or ``ready_for_next``) that signals the workflow processor where to
        route next.

    Raises
    ------
    MethodNotAllowed
        If ``method`` is anything other than 'GET' or 'POST'.
    """
    if method not in ['GET', 'POST']:
        raise MethodNotAllowed()

    submission, _ = get_submission(submission_id)

    workspace = current_app.api.get_file_store().get_workspace(
        submission_id=submission.submission_id)
    form = ReviewForm(params)

    rdata = {
        'submission_id': submission_id,
        'submission': submission,
        'workspace': workspace,
        'form': form,
        'preflight_files': {},
        'file_notes': {},
    }

    if not workspace:
        return return_to_parent_stage((rdata, status.OK, {}))

    if method == 'GET':
        preflight_data, user_decisions_data = _load_or_create_preflight(submission_id, params, session, token, workspace)

        if preflight_data is None:
            alerts.flash_warning(
                f"We couldn't load preflight data for this submission. {SUPPORT}",
                title="Preflight unavailable")
            return stay_on_this_stage((rdata, status.OK, {}))

        rdata['file_notes'] = dm.get_files_from_preflight(preflight_data)
        _populate_form(form, preflight_data, user_decisions_data)
        rdata['immediate_notifications'] = _get_notifications(submission_id, preflight_data)
        return stay_on_this_stage((rdata, status.OK, {}))

    elif method == 'POST':
        has_changes = _update_preflight(params, submission_id, workspace)

        if has_changes:
            return return_to_parent_stage((rdata, status.OK, {}))
        else:
            _load_or_create_directives(params, session, submission_id, token)
            return ready_for_next((rdata, status.OK, {}))


def _get_zzrm_data(workspace: Workspace, submission_id: str) -> Optional[dict]:
    if not any(f.name == '00README.json' for f in workspace.files):
        return None
    blob = current_app.api.get_file_store().get_source_file(submission_id=submission_id, path='00README.json')
    if isinstance(blob, FileDoesNotExist):
        return None
    return json.loads(blob.download_as_text())

def _get_preflight_data(submission_id: str) -> Optional[dict]:
    blob = current_app.api.get_file_store().get_preflight(submission_id=submission_id)
    if isinstance(blob, FileDoesNotExist):
        return None
    return json.loads(blob.download_as_text())

def _get_user_decisions_data(submission_id: str) -> Optional[dict]:
    blob = current_app.api.get_file_store().get_user_decisions(submission_id=submission_id)
    if isinstance(blob, FileDoesNotExist):
        return None
    return json.loads(blob.download_as_text())

def _update_preflight(params: MultiDict, submission_id: str, workspace: Workspace) -> bool:
    existing_paths = {f.path for f in workspace.files}
    files_to_delete = [p for p in params.getlist('selected_files') if p in existing_paths]

    compiler_version = params.get('compiler_version', '')
    new_decisions = {
        'sources': [{'filename': params.get('source_file', ''), 'usage': 'toplevel'}],
        'texlive_version': compiler_version,
        'process': {
            'compiler': params.get('compiler', ''),
            'compiler_version': compiler_version,
        },
    }
    decisions_changed = new_decisions != (_get_user_decisions_data(submission_id) or {})

    has_changes = bool(files_to_delete) or decisions_changed
    if not has_changes:
        return False

    file_store = current_app.api.get_file_store()
    file_store.delete_preflight(submission_id)
    file_store.store_user_decisions(submission_id, new_decisions)
    for path in files_to_delete:
        file_store.delete_source_file(submission_id, path)

    return True


def _populate_form(form: ReviewForm, preflight_data: Optional[dict], user_decisions_data: Optional[dict]) -> list:
    form.compiler.choices = [(c.value, c.value) for c in Compilation.SupportedCompiler]
    form.compiler_version.choices = [(v.value, f'TeX Live {v.value}') for v in Compilation.CompilerVersion]
    tex_files = [f['filename'] for f in preflight_data.get('tex_files', [])]
    form.source_file.choices = [(f, f) for f in tex_files]

    opts = user_decisions_data or {}
    form.source_file.data = (
        (opts.get('sources') or [{}])[0].get('filename')
        or (preflight_data.get('detected_toplevel_files') or [{}])[0].get('filename', '')
    )
    form.compiler.data = (
        opts.get('process', {}).get('compiler')
        or Compilation.SupportedCompiler.PDFLATEX.value
    )
    form.compiler_version.data = (
        opts.get('process', {}).get('compiler_version')
        or opts.get('texlive_version')
        or Compilation.CompilerVersion.TEXLIVE_2025.value
    )


def _load_or_create_preflight(submission_id: str, params: MultiDict, session: Session, token: str, workspace) -> tuple[Optional[dict], Optional[dict]]:
    """Returns preflight and user_decisions"""
    preflight_data = _get_preflight_data(submission_id)
    zzrm_data = None
    if preflight_data is None:
        file_store = current_app.api.get_file_store()
        # if there is no preflight, then there wouldn't be a user decisions file.
        #   check if there is a zzrm, and use that as initial user decisions.
        zzrm_data = _get_zzrm_data(workspace, submission_id)
        if zzrm_data is not None:
            zzrm_data = dm.convert_zzrm_to_user_decisions(zzrm_data)
            file_store.store_user_decisions(submission_id, zzrm_data)
            file_store.delete_source_file(submission_id, '00README.json')

        # user_decisions + preflight + compile logs -> directives.json
        file_store.delete_directives(submission_id)

        start_preflight(params, session, submission_id, token)
        preflight_data = _get_preflight_data(submission_id)

    # If there is no zzrm found above, then check if there is a user decisions file,
    #   which may have been created already, if the user has made selections before.
    user_decisions_data = None
    if zzrm_data == None:
        user_decisions_data = _get_user_decisions_data(submission_id)

    return preflight_data, user_decisions_data or zzrm_data


def _load_or_create_directives(params: MultiDict, session: Session, submission_id: str, token: str) -> None:
    file_store = current_app.api.get_file_store()
    if not file_store.does_directives_exist(submission_id):
        start_directives(params, session, submission_id, token)


def _get_notifications(submission_id: str, preflight_data: Optional[dict]) -> List[Dict[str, str]]:
    notifications = []
    if preflight_data is not None:
        notifications.append({
            'title': 'Preflight complete',
            'severity': 'success',
            'body': 'Your files have been analyzed.',
        })
    else:
        notifications.append({
            'title': 'Preflight pending',
            'severity': 'warning',
            'body': 'Preflight analysis is not yet available for your files.',
        })

    if current_app.api.get_file_store().does_directives_exist(submission_id):
        notifications.append({
            'title': 'Directives ready',
            'severity': 'success',
            'body': 'Compilation directives have been generated.',
        })
    else:
        notifications.append({
            'title': 'Directives pending',
            'severity': 'info',
            'body': 'Compilation directives have not yet been generated.',
        })

    return notifications


def start_preflight(params: MultiDict, session: Session, submission_id: str,
                    token: str, **kwargs) -> Response:
    submitter, client = user_and_client_from_session(session)
    submission, _ = get_submission(submission_id)
    form = ReviewForm(params)
    response_data = {
        'submission_id': submission_id,
        'submission': submission,
        'form': form,
        'status': None,
    }

    command = StartPreflight(creator=submitter, client=client)
    if validate_command(form, command, submission):
        try:
            current_app.api.save(command, submission_id=submission.submission_id)
        except SaveError as e:
            alerts.flash_failure(f"We couldn't start preflight. {SUPPORT}", title="Preflight failed")
            raise InternalServerError(response_data) from e
        

def start_directives(params: MultiDict, session: Session, submission_id: str,
                    token: str, **kwargs) -> Response:
    submitter, client = user_and_client_from_session(session)
    submission, _ = get_submission(submission_id)
    form = ReviewForm(params)
    response_data = {
        'submission_id': submission_id,
        'submission': submission,
        'form': form,
        'status': None,
    }

    command = StartDirectives(creator=submitter, client=client)
    if validate_command(form, command, submission):
        try:
            current_app.api.save(command, submission_id=submission.submission_id)
        except SaveError as e:
            alerts.flash_failure(f"We couldn't start directives. {SUPPORT}", title="Directives failed")
            raise InternalServerError(response_data) from e