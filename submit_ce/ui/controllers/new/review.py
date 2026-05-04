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
from submit_ce.domain.event.process import StartPreflight
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

# directive_manager2 uses the submission-tools code.
# directive_manager just parses the json.
from submit_ce.implementations.compile.directive_manager2 import DirectiveManager

logger = logging.getLogger(__name__)

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103

'''
David says:
    The  gcp_preflight is the original response, then we convert it to the
directives data that the UI uses. The 00README is the final output 
that lives with the article forever.
    00README.json is 'human' curated result of directives input and 
choices made in the UI.
    The Review Files page allows the submitter to make choices by looking
at the presentation from the directives (digested preflight + tree).
These choices are then written to the 00README.json file that sits
with the submission source files. 00README.json lives with the article
source forever.


Thoughts for review_files:

Files used:
- [id]/gcp_preflight.json
- [id]/directives.json
- [id]/src/00README.json

Right now, the tex2pdf-api reads the submission .tar.gz.
This means any files deleted by this form will be deleted from src/
but will still be reads from the zip, loaded into the workspace, and displayed in the html table.

The workflow could be:
- create preflight if not exists. create directives if not exists.
- use directives to show form to user.
- save changes to both directives and zzrm.

We should be able to work only from src/
- The legacy add-files had a re-compress and download button. 
- And legacy seems to keep src/ in sync with .tar.gz
- We probably need a zip and download button.

TODO:
- in start_preflight(): uncomment validate
- add tests.
- in html file list, sort, remove duplicates, propose deletes.
- fix the format of the zzrm.
'''

class ReviewForm(csrf.CSRFForm):
    """Form for reviewing files and selecting compilation options."""
    
    # These choices will be populated dynamically in the controller
    source_file = SelectField('Select main source file', validators=[DataRequired()])
    compiler = SelectField('Select compiler', validators=[DataRequired()])
    compiler_version = SelectField('Select compiler version', validators=[DataRequired()])

    has_directives = False
    has_preflight = False
    has_zzrm = False


def review_files(method: str, params: MultiDict, session: Session,
                 submission_id: str, token: str, **kwargs) -> Response:

    if method not in ['GET', 'POST']:
        raise MethodNotAllowed()

    submission, _ = get_submission(submission_id)

    workspace = current_app.api.get_file_store().get_workspace(
        submission_id=submission.submission_id)
    if not workspace:
        raise "Missing workspace"

    form = ReviewForm(params)

    rdata = {
        'submission_id': submission_id,
        'submission': submission,
        'workspace': workspace,
        'form': form,
        'preflight_files': {},
        'file_notes': {},
    }

    directive_dict = load_or_create_directives(params, session, submission_id, token, form, workspace)

    if method == 'GET':
        populate_form_from_directives(form, workspace, directive_dict)
        rdata['preflight_files'] = directive_dict.get('preflight', {})
        rdata['file_notes'] = build_file_notes(directive_dict)
        return stay_on_this_stage((rdata, status.OK, {}))

    elif method == 'POST':
        has_changes = update_directives(params, submission_id, workspace)
        _save_zzrm(params, submission_id)
        if has_changes:
            return return_to_parent_stage((rdata, status.OK, {}))
        else:
            return ready_for_next((rdata, status.OK, {}))


def update_directives(params: MultiDict, submission_id: str, workspace: Workspace) -> bool:
    files_to_delete = set(params.getlist('selected_files'))
    file_store = current_app.api.get_file_store()
    deleted = False

    for f in workspace.files:
        if f.name in files_to_delete:
            file_store.delete_source_file(submission_id, f.path)
            deleted = True
    if deleted:
        file_store.delete_preflight(submission_id)
        file_store.delete_directives(submission_id)
    return deleted


def populate_form_from_directives(form: ReviewForm, workspace: Workspace, directive_text: dict) -> None:
    directives = directive_text.get("directives", {})
    suggested_source = (directives.get("sources") or [{}])[0].get("filename", "")
    tex_files = [f.path for f in workspace.files if f.path.endswith(".tex")]
    source_choices = [(f, f) for f in tex_files] or [(suggested_source, suggested_source)]
    form.source_file.choices = source_choices
    form.source_file.data = suggested_source

    compiler_choices = [(c.value, c.value) for c in Compilation.SupportedCompiler]
    form.compiler.choices = compiler_choices
    form.compiler.data = directives.get("process", {}).get(
        "compiler", Compilation.SupportedCompiler.PDFLATEX.value)

    version_choices = [(v.value, v.value) for v in Compilation.CompilerVersion]
    form.compiler_version.choices = version_choices
    form.compiler_version.data = directives.get("process", {}).get(
        "compiler_version", Compilation.CompilerVersion.TEXLIVE_2025.value)


def build_file_notes(directive_dict: dict) -> dict:
    """Return {filename: notes_string} for the Auto-detected Notes column.

    Collects each file's category membership and issues from the preflight
    section of directive_dict, deduplicating across categories.
    """
    preflight = directive_dict.get('preflight', {})
    categories = [
        ('Top-level',  preflight.get('detected_toplevel_files', [])),
        ('TeX',        preflight.get('tex_files', [])),
        ('Ancillary',  preflight.get('ancillary_files', [])),
        ('Maybe used', preflight.get('maybe_used_files', [])),
        ('Image',      preflight.get('image_files', [])),
    ]

    seen: dict = {}
    for label, files in categories:
        for f in files:
            filename = f.get('filename', '')
            if not filename:
                continue
            entry = seen.setdefault(filename, {'categories': [], 'issues': []})
            entry['categories'].append(label)
            entry['issues'].extend(f.get('issues', []))

    result = {}
    for filename, info in seen.items():
        parts = [', '.join(info['categories'])]
        if info['issues']:
            parts.append('; '.join(str(i) for i in info['issues']))
        result[filename] = ' — '.join(parts)
    return result


def _save_zzrm(params: MultiDict, submission_id: str) -> None:
    zzrm = {
        'sources': [{'filename': params.get('source_file', '')}],
        'process': {
            'compiler': params.get('compiler', ''),
            'compiler_version': params.get('compiler_version', ''),
        }
    }
    current_app.api.get_file_store().store_zzrm(submission_id, zzrm)


def _get_zzrm_text(workspace: Workspace, submission_id: str) -> Optional[str]:
    if not any(f.name == '00README.json' for f in workspace.files):
        return None
    blob = current_app.api.get_file_store().get_source_file(submission_id=submission_id, path='00README.json')
    if isinstance(blob, FileDoesNotExist):
        return None
    return blob.download_as_text()

def _get_directives_text(submission_id: str) -> Optional[str]:
    blob = current_app.api.get_file_store().get_directives(submission_id=submission_id)
    if isinstance(blob, FileDoesNotExist):
        return None
    return blob.download_as_text()

def _get_preflight_text(submission_id: str) -> Optional[str]:
    blob = current_app.api.get_file_store().get_preflight(submission_id=submission_id)
    if isinstance(blob, FileDoesNotExist):
        return None
    return blob.download_as_text()


def load_or_create_directives(
        params: MultiDict, 
        session: Session,
        submission_id: str, 
        token: str,
        form: ReviewForm,
        workspace,
) -> dict:
    # The user may have included a 00Readme file.
    zzrm_text = _get_zzrm_text(workspace, submission_id)
    if zzrm_text != None:
        form.has_zzrm = True

    # tex2pdf-api may have already been run, to create this file.
    preflight_text = _get_preflight_text(submission_id)
    if preflight_text != None:
        form.has_preflight = True

    # always load directives, to get user selections.
    directives_text = _get_directives_text(submission_id)
    if directives_text != None:
        form.has_directives = True

    # If preflight does not exist, it needs to be created.
    # Run it as an event, because tex2pdf may take longer than this code's timeout.
    # Other actions are just loading files, so do not need to be tracked.
    if preflight_text == None:
        start_preflight(params, session, submission_id, token)
        preflight_text = _get_preflight_text(submission_id)

    # Will need to decide what to do about test_integration.py
    if isinstance(preflight_text, FileDoesNotExist):
        raise InternalServerError("Preflight not yet created.")

    if directives_text == None:
        directives_text = "" # this is a hack, to minimize changes to the legacy submission_tools.
    if preflight_text is None:
        return {}

    directive_dict = DirectiveManager().convert_preflight_to_directives(zzrm_text, preflight_text)
    current_app.api.get_file_store().store_directives(
        submission_id=submission_id,
        content=directive_dict,
    )
    return directive_dict

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

    #if not form.validate():
    #    return stay_on_this_stage((response_data, status.OK, {}))

    command = StartPreflight(creator=submitter, client=client)
    if validate_command(form, command, submission):
        try:
            current_app.api.save(command, submission_id=submission.submission_id)
        except SaveError as e:
            alerts.flash_failure(f"We couldn't start preflight. {SUPPORT}", title="Preflight failed")
            raise InternalServerError(response_data) from e
