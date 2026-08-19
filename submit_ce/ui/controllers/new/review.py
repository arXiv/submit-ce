import json
import logging
from http import HTTPStatus as status
from typing import Tuple, Dict, Any, Optional, List

import httpx
from flask import current_app
from arxiv.auth.domain import Session
from arxiv.base import alerts
from markupsafe import Markup
from submit_ce.domain.event.process import (
    SetDecisions,
    SetDirectivesAndCleanup,
    StartPreflight,
    StartDirectives,  # noqa: F401 (StartDirectives used below)
    StoreZzrm,
)
from submit_ce.domain.event import SetSourceFormat
from ...auth import user_and_client_from_session
from arxiv.files import FileDoesNotExist
from arxiv.forms import csrf
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import (
    InternalServerError,
    MethodNotAllowed,
)
from wtforms import SelectField
from wtforms.validators import DataRequired

from submit_ce.domain.uploads import Workspace, SourceFormat
from submit_ce.domain.exceptions import InvalidEvent, SaveError
from submit_ce.ui.controllers.util import validate_command
from submit_ce.ui.preflight.issues import (
    build_issue_context, has_blocking_issues, group_notifications_by_severity,
)
from submit_ce.ui.preflight.file_context import build_file_rows
from submit_ce.ui.routes.flow_control import (
    stay_on_this_stage, ready_for_next, return_to_parent_stage,
    return_to_previous_stage, advance_to_current,
)
from submit_ce.ui.backend import get_submission
from submit_ce.ui import SUPPORT

from submit_ce.domain.compilation import Compilation

from submit_ce.implementations.compile.directive_manager import DirectiveManager as dm

from tex2pdf_tools.zerozeroreadme import ZeroZeroReadMe
from tex2pdf_tools.preflight import PreflightResponse

logger = logging.getLogger(__name__)
#logging.basicConfig(level=logging.DEBUG)

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
    submitter, client = user_and_client_from_session(session)
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
        'selected_top_level_files': [],
        'top_level_candidates': [],
        'file_issues': {},
        'recompute': {'edges': {}, 'candidates': [], 'maybe_used': []},
    }

    if not workspace:
        return return_to_parent_stage((rdata, status.OK, {}))

    if submission.source_format == SourceFormat.PDF:
        return advance_to_current((rdata, status.OK, {}))

    if submission.source_format != SourceFormat.TEX:
        return return_to_previous_stage((rdata, status.OK, {}))

    if method == 'GET':
        preflight_data, user_decisions_data = _load_or_create_preflight(
            submission_id, params, session, token, workspace, submitter, client
        )

        if preflight_data is None:
            # Preflight is what populates compiler choices, top-level TeX
            # candidates, and per-file usage notes. Without it, the form
            # below has nothing to render -- the template hides the form
            # sections when file_notes is empty and surfaces this flash
            # message + the main-area placeholder instead.
            alerts.flash_warning(
                Markup(
                    "We couldn't analyze the files in your submission "
                    "right now because the preflight service is "
                    "temporarily unavailable. Please refresh this page "
                    "to try again. ") + SUPPORT,
                title="Preflight unavailable")
            return stay_on_this_stage((rdata, status.OK, {}))

        return _render_review_page(rdata, form, submission_id,
                                   preflight_data, user_decisions_data)

    elif method == 'POST':
        # _update_preflight persists the submitted decisions and returns True only
        # when preflight was invalidated (a file was deleted). A selection-only
        # change (compiler / top-level) keeps preflight valid, so we fall through
        # and advance rather than bouncing to Upload for a needless re-scan.
        preflight_invalidated = _update_preflight(params, submission_id, workspace, submitter, client)

        if preflight_invalidated:
            return return_to_parent_stage((rdata, status.OK, {}))
        else:
            preflight_data, user_decisions_data = _load_or_create_preflight(
                submission_id, params, session, token, workspace, submitter, client)

            if preflight_data is None:
                alerts.flash_warning(
                    f"Preflight data is not available for this submission. {SUPPORT}",
                    title="Cannot generate directives")
                return stay_on_this_stage((rdata, status.OK, {}))

            # SUBMISSION-216: a danger-severity preflight issue blocks
            # Continue -- mirrors 1.5's hasPreflightBlockers. Re-render Review
            # Files with the issue banners instead of advancing.
            if has_blocking_issues(preflight_data):
                # danger issue(s) present -> re-render with the "Cannot continue"
                # card (added by _render_review_page) instead of advancing.
                return _render_review_page(rdata, form, submission_id,
                                           preflight_data, user_decisions_data)

            _load_or_create_directives(params, session, submission_id, token)

            zzrm = ZeroZeroReadMe()
            if user_decisions_data:
                zzrm.from_dict(user_decisions_data)
            zzrm.update_from_preflight(PreflightResponse(**preflight_data))
            logger.warning("ZeroZeroReadMe after update_from_preflight: %s", zzrm.to_json())
            # Write 00README.json under the submission row lock and invalidate
            # the now-stale source package, rather than a bare (unlocked)
            # store_zzrm call. See StoreZzrm and the critical-section note in
            # CLAUDE.md. [SUBMISSION-205]
            current_app.api.save(
                StoreZzrm(creator=submitter, client=client, zzrm=zzrm.to_dict()),
                submission_id=submission_id,
            )

            return ready_for_next((rdata, status.OK, {}))


def _render_review_page(rdata, form, submission_id, preflight_data,
                        user_decisions_data):
    """Populate ``rdata`` for the Review Files template and stay on the stage.

    Shared by the GET path and the danger-gate on POST so both render the
    same page (file table, per-file badges, severity-grouped issue banners).
    Also sets ``has_blocking_issues`` so the template can reflect the blocked
    state. Returns a ``stay_on_this_stage`` flow-control result.
    """
    _populate_form(form, preflight_data, user_decisions_data)
    # Reflect ALL persisted top-levels, in order (SUBMISSION-170), so every
    # selected top-level is protected/rendered -- not just the one in the single
    # dropdown. Falls back to the form's single selection on a fresh page (no
    # user_decisions yet).
    selected_top_level_files = (
        _ordered_top_level_filenames(user_decisions_data)
        or [f for f in [form.source_file.data] if f]
    )
    rdata['selected_top_level_files'] = selected_top_level_files
    # Candidate top-level TeX files for the multi-select UI (SUBMISSION-226).
    # `_populate_form` set `source_file.choices` to the detected tex files;
    # the template builds each `top_level_tex_files[]` dropdown from this list.
    rdata['top_level_candidates'] = [c[0] for c in form.source_file.choices]
    # Surface preflight issues (SUBMISSION-210): reason-code-grouped banners
    # + per-file badges, extracted server-side. Issue banners lead; the
    # backend-status cards follow.
    issue_notifications, file_issues = build_issue_context(preflight_data)
    rdata['file_issues'] = file_issues
    # SUBMISSION-219: fold the per-file badges and the top-level / README
    # flags into each file row so the template renders fields from one object
    # instead of computing them inline (and re-deriving them from separate
    # file_issues / selected_top_level_files parameters). Gives a single
    # per-file object to extend with used/unused + delete defaults later.
    #
    # SUBMISSION-231: root "used" at the current top-level selection. The set of
    # files reachable from the selected top-level(s) drives is_used/is_unused, so
    # the auto-detected notes (and the auto-checked-for-deletion defaults) reflect
    # THIS selection rather than a flat union over every tex file. No preflight
    # re-run -- the edges are already in the report (see reachable_from).
    used_filenames = dm.reachable_from(selected_top_level_files, preflight_data)
    rdata['file_notes'] = build_file_rows(
        dm.get_files_from_preflight(preflight_data),
        file_issues,
        selected_top_level_files,
        used_filenames,
    )
    # SUBMISSION-231 (part 2): data for the client-side live recompute. The same
    # resolved-edge graph the server walked (used_edges), plus the detected
    # top-level candidates and the coarse maybe-used set, so review_used_recompute.js
    # can re-root used/unused in the browser as the top-level selection changes --
    # display only, persisting/deleting nothing until Continue. Candidates are
    # never auto-checked for deletion (a file the submitter might pick next).
    rdata['recompute'] = {
        'edges': dm.used_edges(preflight_data),
        # Detected top-level files (the genuine alternative "mains"): never
        # auto-check one for deletion, since the submitter might select it next.
        # This is preflight's detected set, NOT every tex candidate in the dropdown.
        'candidates': [t.get('filename') for t
                       in (preflight_data.get('detected_toplevel_files') or [])
                       if t.get('filename')],
        'maybe_used': [f for f in (preflight_data.get('maybe_used_files') or []) if f],
    }
    rdata['has_blocking_issues'] = any(
        n.get('severity') == 'danger' for n in issue_notifications)
    # SUBMISSION-218: collapse the per-code issue banners into one card
    # per severity (danger / warning / info) so the page isn't a long stack.
    cards = group_notifications_by_severity(issue_notifications)
    if rdata['has_blocking_issues']:
        # A persistent danger summary card explaining the block leads the
        # list (rendered on GET too, since the button stays enabled).
        cards = [{
            'title': 'Cannot continue',
            'severity': 'danger',
            'body': 'Please resolve the highlighted problem(s) before you can continue.',
        }] + cards
    rdata['immediate_notifications'] = cards
    # The passive "preflight complete" / "directives" status cards are
    # dropped entirely (per UI-design review) -- the main column is reserved for
    # issues that need the submitter's attention, and nothing replaces them in
    # the sidebar.
    return stay_on_this_stage((rdata, status.OK, {}))


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

def _ordered_top_level_filenames(user_decisions_data: Optional[dict]) -> list[str]:
    """Ordered, de-duped top-level filenames from persisted user_decisions.

    Reads the ``sources`` list (the ordered set written by ``_update_preflight``)
    so multiple selected top-levels round-trip in order on reload
    (SUBMISSION-170). Returns ``[]`` when there are none.
    """
    sources = (user_decisions_data or {}).get('sources') or []
    out: list[str] = []
    for src in sources:
        filename = src.get('filename')
        if filename and filename not in out:
            out.append(filename)
    return out


def _selected_top_level_files(params: MultiDict) -> list[str]:
    """Return the top-level TeX file(s) the user has selected, in order.

    Supports the current single ``source_file`` field and a future multi-select
    (``top_level_tex_files[]``), so the delete guard already handles one or more
    selected top-level files (SUBMISSION-209).
    """
    values = list(params.getlist('source_file')) + \
        list(params.getlist('top_level_tex_files[]'))
    seen: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen


def _update_preflight(params: MultiDict, submission_id: str, workspace: Workspace, submitter, client) -> bool:
    existing_paths = {f.path for f in workspace.files}
    files_to_delete = [p for p in params.getlist('selected_files') if p in existing_paths]

    # Never delete files the submission needs: the selected top-level TeX
    # file(s) (SUBMISSION-209) and any file needed by that selection
    # (SUBMISSION-221 / SUBMISSION-231). maybe-used and unused files stay
    # deletable. The template disables these checkboxes, but a crafted or stale
    # POST can still carry them, so we filter here and warn. The authoritative
    # guard is in SetDecisions.execute (via protected_sources), which runs under
    # the submission row lock.
    #
    # "used" is rooted at the top-level(s) being saved (SUBMISSION-231): a file
    # protected because it's reachable from the OLD top-level should become
    # deletable once the submitter switches away from it. reachable_from re-roots
    # over the existing preflight edges -- no re-scan.
    selected_top_levels = _selected_top_level_files(params)
    used_files = dm.reachable_from(selected_top_levels, _get_preflight_data(submission_id) or {})
    protected_set = set(selected_top_levels) | used_files
    protected = [p for p in files_to_delete if p in protected_set]
    if protected:
        files_to_delete = [p for p in files_to_delete if p not in protected_set]
        alerts.flash_warning(
            "We kept files your submission needs and did not delete them: "
            f"{', '.join(protected)}. A top-level TeX file can be freed for "
            "deletion by removing it from the Top-Level TeX selection; a "
            "referenced file must first be unreferenced in your source.",
            title="Files not deleted")

    # If the POST carries none of the review-form fields, the user clicked
    # "next" without changing anything; don't invalidate preflight.
    form_fields_present = any(params.get(k) for k in
                              ('source_file', 'compiler', 'compiler_version'))
    if not form_fields_present and not files_to_delete:
        return False

    # Persist ALL selected top-level TeX files, in submission order, so multiple
    # ordered top-levels round-trip (SUBMISSION-170). `selected_top_levels`
    # comes from `_selected_top_level_files` (source_file + top_level_tex_files[]).
    # For today's single-dropdown UI this is a one-item list -- identical to the
    # previous single-source behavior -- so it's a no-op until the multi-select UI
    # lands (SUBMISSION-226).
    new_decisions = {
        'sources': [{'filename': f} for f in selected_top_levels],
        'texlive_version': params.get('compiler_version', ''),
        'process': {
            'compiler': params.get('compiler', ''),
        },
    }
    decisions_changed = new_decisions != (_get_user_decisions_data(submission_id) or {})

    has_changes = bool(files_to_delete) or decisions_changed
    if not has_changes:
        return False

    try:
        cmd = SetDecisions(creator=submitter, client=client,
                           decisions=new_decisions, files_to_delete=files_to_delete,
                           protected_sources=sorted(used_files))
        current_app.api.save(cmd, submission_id=submission_id)
        # Return whether PREFLIGHT was invalidated. Only a change to the file *set*
        # (a deletion) invalidates it, so the caller returns to Upload to re-run the
        # scan. A selection-only change (compiler / top-level) keeps preflight valid
        # -- SetDecisions regenerated directives but left the report -- so the caller
        # can advance without a re-scan. (SUBMISSION-215)
        return bool(files_to_delete)
    except InvalidEvent:
        # TODO Somehow inform the user
        return False


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


def _load_or_create_preflight(
    submission_id: str,
    params: MultiDict,
    session: Session,
    token: str,
    workspace,
    submitter,
    client,
) -> tuple[Optional[dict], Optional[dict]]:
    """Returns preflight and user_decisions"""
    preflight_data = _get_preflight_data(submission_id)
    zzrm_data = None
    if preflight_data is None:
        # if there is no preflight, then there wouldn't be a user decisions file.
        #   check if there is a zzrm, and use that as initial user decisions.
        raw_zzrm = _get_zzrm_data(workspace, submission_id)
        zzrm_data = (
            dm.convert_zzrm_to_user_decisions(raw_zzrm)
            if raw_zzrm is not None else None
        )

        # Cleanup (seed user_decisions, drop 00README, clear stale
        # directives.json) runs through api.save so the mutations
        # happen inside the per-submission row lock — no concurrent
        # upload can interleave between cleanup and start_preflight.
        try:
            current_app.api.save(
                SetDirectivesAndCleanup(
                    creator=submitter,
                    client=client,
                    user_decisions_from_zzrm=zzrm_data,
                ),
                submission_id=submission_id,
            )
        except InvalidEvent:
            pass  # nothing actionable in cleanup is fine

        # Preflight calls into the external tex2pdf service; that service
        # may be unreachable (local dev without the service running, a
        # transient outage in production, etc.). If it fails, log and
        # continue with preflight_data=None -- review_files() already has
        # a clean handler for that case (flashes "Preflight unavailable"
        # and stays on this stage) instead of bubbling up as a 500.
        try:
            start_preflight(params, session, submission_id, token)
        except Exception as exc:
            logger.warning(
                "Could not run preflight for submission %s: %s",
                submission_id, exc,
            )
        preflight_data = _get_preflight_data(submission_id)
        _store_source_format(preflight_data, session, submission_id)


    # If there is no zzrm found above, then check if there is a user decisions file,
    #   which may have been created already, if the user has made selections before.
    user_decisions_data = None
    if zzrm_data is None:
        user_decisions_data = _get_user_decisions_data(submission_id)

    return preflight_data, user_decisions_data or zzrm_data


def _store_source_format(preflight_data: Optional[dict], session: Session,
                         submission_id: str) -> None:
    """Record the preflight-detected `lang` as the submission source_format."""
    if not preflight_data:
        return
    lang = dm.get_lang_from_preflight(preflight_data)
    if lang is None:
        return
    submitter, client = user_and_client_from_session(session)
    command = SetSourceFormat(source_format=lang,
                              creator=submitter, client=client)
    try:
        current_app.api.save(command, submission_id=submission_id)
    except SaveError as e:
        logger.warning(
            f"Could not save SetSourceFormat for {submission_id}: {e}")


def _load_or_create_directives(params: MultiDict, session: Session, submission_id: str, token: str) -> None:
    file_store = current_app.api.get_file_store()
    if not file_store.does_directives_exist(submission_id):
        start_directives(params, session, submission_id, token)


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
        except httpx.HTTPError as e:
            logger.error('Compile service error during StartDirectives for %s: %s',
                         submission_id, e)
            alerts.flash_failure(
                f"We couldn't start directives because the compile service"
                f" is unavailable. {SUPPORT}",
                title="Directives failed")
            raise InternalServerError(response_data) from e
