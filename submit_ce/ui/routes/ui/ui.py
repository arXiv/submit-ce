"""Provides routes for the submission user interface."""

from typing import Optional, Callable, Dict, List, Union, Any

from arxiv.auth.auth import scopes
from arxiv.auth.auth.decorators import scoped
from flask import Blueprint, make_response, redirect, request, \
    render_template, url_for, send_file
from flask import Response as FResponse
from markupsafe import Markup
from werkzeug.datastructures import MultiDict
from werkzeug import Response as WResponse
from werkzeug.exceptions import ServiceUnavailable

from arxiv.base import logging, alerts

from ..auth import is_owner
from ... import util
from submit_ce.ui.controllers import ui as cntrls
from submit_ce.ui.controllers.ui.new import upload
from submit_ce.ui.controllers.ui.new import upload_delete

from submit_ce.ui.workflow.stages import FileUpload

from submit_ce.ui.workflow.processor import WorkflowProcessor

from .flow_control import flow_control, get_workflow, endpoint_name

logger = logging.getLogger(__name__)

UI = Blueprint('ui', __name__, url_prefix='/')

SUPPORT = Markup(
    'If you continue to experience problems, please contact'
    ' <a href="mailto:help@arxiv.org"> arXiv support</a>.'
)

Response = Union[FResponse, WResponse]


def redirect_to_login(*args, **kwargs) -> str:
    """Send the unauthorized user to the log in page."""
    return redirect(url_for('login'))


@UI.before_request
def load_submission() -> None:
    """Load the submission before the request is processed."""
    if request.view_args is None or 'submission_id' not in request.view_args:
        return
    submission_id = request.view_args['submission_id']

    request.submission, request.events = \
        util.load_submission(submission_id)

    wfp = get_workflow(request.submission)
    request.workflow = wfp
    request.current_stage = wfp.current_stage()
    request.this_stage = wfp.workflow[endpoint_name()]


@UI.context_processor
def inject_workflow() -> Dict[str, Optional[WorkflowProcessor]]:
    """Inject the current workflow into the template rendering context."""
    rd = {}
    if hasattr(request, 'workflow'):
        rd['workflow'] = request.workflow
        if hasattr(request, 'current_stage'):
            rd['get_current_stage_for_submission'] = request.current_stage
        if hasattr(request, 'this_stage'):
            rd['this_stage'] = request.this_stage
        return rd

    # TODO below is unexpected: why are we setting this to a function?
    return {'workflow': None, 'get_workflow': get_workflow}


def add_immediate_alert(context: dict, severity: str,
                        message: Union[str, dict], title: Optional[str] = None,
                        dismissable: bool = True, safe: bool = False) -> None:
    """Add an alert for immediate display."""
    if safe and isinstance(message, str):
        message = Markup(message)
    data = {'message': message, 'title': title, 'dismissable': dismissable}

    if 'immediate_alerts' not in context:
        context['immediate_alerts'] = []
    context['immediate_alerts'].append((severity, data))


def handle(controller: Callable, template: str, title: str,
           submission_id: Optional[int] = None,
           get_params: bool = False, flow_controlled: bool = False,
           **kwargs: Any) -> Response:
    """
    Generalized request handling pattern.

    Parameters
    ----------
    controller : callable
        A controller function with the signature ``(method: str, params:
        MultiDict, session: Session, submission_id: int, token: str) ->
        Tuple[dict, int, dict]``
    template : str
        HTML template to use in the response.
    title : str
        Page title, if not provided by controller.
    submission_id : int or None
    get_params : bool
        If True, GET parameters will be passed to the controller on GET
        requests. Default is False.
    kwargs : kwargs
        Passed as ``**kwargs`` to the controller.

    Returns
    -------
    :class:`.Response`

    """
    response: Response
    logger.debug('Handle call to controller %s with template %s, title %s,'
                 ' and ID %s', controller, template, title, submission_id)
    if request.method == 'GET' and get_params:
        request_data = MultiDict(request.args.items(multi=True))
    else:
        request_data = MultiDict(request.form.items(multi=True))

    context = {'pagetitle': title}

    data, code, headers = controller(request.method, request_data,
                                     request.auth, submission_id,
                                     **kwargs)
    context.update(data)

    if flow_controlled:
        return (data, code, headers,
                lambda: make_response(render_template(template, **context), code))
    if code < 300:
        response = make_response(render_template(template, **context), code)
    elif 'Location' in headers:
        response = redirect(headers['Location'], code=code)
    else:
        response = FResponse(response=context, status=code, headers=headers)
    return response


@UI.route('/status', methods=['GET'])
def service_status():
    """Status endpoint."""
    return 'ok'


@UI.route('/', methods=["GET"])
@scoped(scopes.CREATE_SUBMISSION,
                        unauthorized=redirect_to_login)
def manage_submissions():
    """Display the submission management dashboard."""
    return handle(cntrls.create, 'submit_ce/manage_submissions.html',
                  'Manage submissions')


@UI.route('/', methods=["POST"])
@scoped(scopes.CREATE_SUBMISSION,
                        unauthorized=redirect_to_login)
def create_submission():
    """Create a new submission."""
    return handle(cntrls.create, 'submit_ce/manage_submissions.html',
                  'Create a new submission')


@UI.route('/<int:submission_id>/unsubmit', methods=["GET", "POST"])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
def unsubmit_submission(submission_id: int):
    """Unsubmit (unfinalize) a submission."""
    return handle(cntrls.new.unsubmit.unsubmit,
                  'submit_ce/confirm_unsubmit.html',
                  'Unsubmit submission', submission_id)


@UI.route('/<int:submission_id>/delete', methods=["GET", "POST"])
@scoped(scopes.DELETE_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
def delete_submission(submission_id: int):
    """Delete, or roll a submission back to the last announced state."""
    return handle(cntrls.delete.delete,
                  'submit_ce/confirm_delete_submission.html',
                  'Delete submission or replacement', submission_id)


@UI.route('/<int:submission_id>/cancel/<string:request_id>', methods=["GET", "POST"])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
def cancel_request(submission_id: int, request_id: str):
    """Cancel a pending request."""
    return handle(cntrls.delete.cancel_request,
                  'submit_ce/confirm_cancel_request.html', 'Cancel request',
                  submission_id, request_id=request_id)


@UI.route('/<int:submission_id>/replace', methods=["POST"])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
def create_replacement(submission_id: int):
    """Create a replacement submission."""
    return handle(cntrls.new.create.replace, 'submit_ce/replace.html',
                  'Create a new version (replacement)', submission_id)


@UI.route('/<int:submission_id>', methods=["GET"])
@scoped(scopes.VIEW_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
def submission_status(submission_id: int) -> Response:
    """Display the current state of the submission."""
    return handle(cntrls.submission_status, 'submit_ce/status.html',
                  'Submission status', submission_id)


@UI.route('/<int:submission_id>/edit', methods=['GET'])
@scoped(scopes.VIEW_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control()
def submission_edit(submission_id: int) -> Response:
    """Redirects to current edit stage of the submission."""
    return handle(cntrls.submission_edit, 'submit_ce/status.html',
                  'Submission status', submission_id, flow_controlled=True)

# # TODO: remove me!!
# @UI.route(path('announce'), methods=["GET"])
# @scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner)
# def announce(submission_id: int) -> Response:
#     """WARNING WARNING WARNING this is for testing purposes only."""
#     util.announce_submission(submission_id)
#     target = url_for('ui.submission_status', submission_id=submission_id)
#     return Response(response={}, status=status.SEE_OTHER,
#                     headers={'Location': target})
#
#
# # TODO: remove me!!
# @UI.route(path('/place_on_hold'), methods=["GET"])
# @scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner)
# def place_on_hold(submission_id: int) -> Response:
#     """WARNING WARNING WARNING this is for testing purposes only."""
#     util.place_on_hold(submission_id)
#     target = url_for('ui.submission_status', submission_id=submission_id)
#     return Response(response={}, status=status.SEE_OTHER,
#                     headers={'Location': target})
#
#
# # TODO: remove me!!
# @UI.route(path('apply_cross'), methods=["GET"])
# @scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner)
# def apply_cross(submission_id: int) -> Response:
#     """WARNING WARNING WARNING this is for testing purposes only."""
#     util.apply_cross(submission_id)
#     target = url_for('ui.submission_status', submission_id=submission_id)
#     return Response(response={}, status=status.SEE_OTHER,
#                     headers={'Location': target})
#
#
# # TODO: remove me!!
# @UI.route(path('reject_cross'), methods=["GET"])
# @scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner)
# def reject_cross(submission_id: int) -> Response:
#     """WARNING WARNING WARNING this is for testing purposes only."""
#     util.reject_cross(submission_id)
#     target = url_for('ui.submission_status', submission_id=submission_id)
#     return Response(response={}, status=status.SEE_OTHER,
#                     headers={'Location': target})
#
#
# # TODO: remove me!!
# @UI.route(path('apply_withdrawal'), methods=["GET"])
# @scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner)
# def apply_withdrawal(submission_id: int) -> Response:
#     """WARNING WARNING WARNING this is for testing purposes only."""
#     util.apply_withdrawal(submission_id)
#     target = url_for('ui.submission_status', submission_id=submission_id)
#     return Response(response={}, status=status.SEE_OTHER,
#                     headers={'Location': target})
#
#
# # TODO: remove me!!
# @UI.route(path('reject_withdrawal'), methods=["GET"])
# @scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner)
# def reject_withdrawal(submission_id: int) -> Response:
#     """WARNING WARNING WARNING this is for testing purposes only."""
#     util.reject_withdrawal(submission_id)
#     target = url_for('ui.submission_status', submission_id=submission_id)
#     return Response(response={}, status=status.SEE_OTHER,
#                     headers={'Location': target})


@UI.route('/<int:submission_id>/verify_user', methods=['GET', 'POST'])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control()
def verify_user(submission_id: Optional[int] = None) -> Response:
    """Render the submit_ce start page."""
    return handle(cntrls.verify, 'submit_ce/verify_user.html',
                  'Verify User Information', submission_id, flow_controlled=True)


@UI.route('/<int:submission_id>/authorship', methods=['GET', 'POST'])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control()
def authorship(submission_id: int) -> Response:
    """Render step 2, authorship."""
    return handle(cntrls.authorship, 'submit_ce/authorship.html',
                  'Confirm Authorship', submission_id, flow_controlled=True)


@UI.route('/<int:submission_id>/license', methods=['GET', 'POST'])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control()
def license(submission_id: int) -> Response:
    """Render step 3, select license."""
    return handle(cntrls.license, 'submit_ce/license.html',
                  'Select a License', submission_id, flow_controlled=True)


@UI.route('/<int:submission_id>/policy', methods=['GET', 'POST'])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control()
def policy(submission_id: int) -> Response:
    """Render step 4, policy agreement."""
    return handle(cntrls.policy, 'submit_ce/policy.html',
                  'Acknowledge Policy Statement', submission_id,
                  flow_controlled=True)


@UI.route('/<int:submission_id>/classification', methods=['GET', 'POST'])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control()
def classification(submission_id: int) -> Response:
    """Render step 5, choose classification."""
    return handle(cntrls.classification,
                  'submit_ce/classification.html',
                  'Choose a Primary Classification', submission_id,
                  flow_controlled=True)


@UI.route('/<int:submission_id>/cross_list', methods=['GET', 'POST'])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control()
def cross_list(submission_id: int) -> Response:
    """Render step 6, secondary classes."""
    return handle(cntrls.cross_list,
                  'submit_ce/cross_list.html',
                  'Choose Cross-List Classifications', submission_id,
                  flow_controlled=True)


@UI.route('/<int:submission_id>/file_upload', methods=['GET', 'POST'])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control()
def file_upload(submission_id: int) -> Response:
    """Render step 7, file upload."""
    return handle(upload.upload_files, 'submit_ce/file_upload.html',
                  'Upload Files', submission_id, files=request.files,
                  token=request.environ['token'], flow_controlled=True)


@UI.route('/<int:submission_id>/file_delete', methods=["GET", "POST"])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control(FileUpload)
def file_delete(submission_id: int) -> Response:
    """Provide the file deletion endpoint, part of the upload step."""
    return handle(upload_delete.delete_file, 'submit_ce/confirm_delete.html',
                  'Delete File', submission_id, get_params=True,
                  token=request.environ['token'], flow_controlled=True)


@UI.route('/<int:submission_id>/file_delete_all', methods=["GET", "POST"])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control(FileUpload)
def file_delete_all(submission_id: int) -> Response:
    """Provide endpoint to delete all files, part of the upload step."""
    return handle(upload_delete.delete_all,
                  'submit_ce/confirm_delete_all.html', 'Delete All Files',
                  submission_id, get_params=True,
                  token=request.environ['token'], flow_controlled=True)


@UI.route('/<int:submission_id>/file_process', methods=['GET', 'POST'])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control()
def file_process(submission_id: int) -> Response:
    """Render step 8, file processing."""
    return handle(cntrls.process.file_process, 'submit_ce/file_process.html',
                  'Process Files', submission_id, get_params=True,
                  token=request.environ['token'], flow_controlled=True)


@UI.route('/<int:submission_id>/preview.pdf', methods=["GET"])
@scoped(scopes.VIEW_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
# TODO @flow_control(Process)?
def file_preview(submission_id: int) -> Response:
    data, code, headers = cntrls.new.process.file_preview(
        MultiDict(request.args.items(multi=True)),
        request.auth,
        submission_id,
        request.environ['token']
    )
    rv = send_file(data, mimetype=headers['Content-Type'], cache_timeout=0)
    rv.set_etag(headers['ETag'])
    rv.headers['Content-Length'] = len(data)  # type: ignore
    rv.headers['Cache-Control'] = 'no-store'
    return rv


@UI.route('/<int:submission_id>/compilation_log', methods=["GET"])
@scoped(scopes.VIEW_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
# TODO @flow_control(Process) ?
def compilation_log(submission_id: int) -> Response:
    data, code, headers = cntrls.process.compilation_log(
        MultiDict(request.args.items(multi=True)),
        request.auth,
        submission_id,
        request.environ['token']
    )
    rv = send_file(data, mimetype=headers['Content-Type'], cache_timeout=0)
    rv.set_etag(headers['ETag'])
    rv.headers['Cache-Control'] = 'no-store'
    return rv


@UI.route('/<int:submission_id>/add_metadata', methods=['GET', 'POST'])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control()
def add_metadata(submission_id: int) -> Response:
    """Render step 9, metadata."""
    return handle(cntrls.metadata, 'submit_ce/add_metadata.html',
                  'Add or Edit Metadata', submission_id, flow_controlled=True)


@UI.route('/<int:submission_id>/add_optional_metadata', methods=['GET', 'POST'])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control()
def add_optional_metadata(submission_id: int) -> Response:
    """Render step 9, metadata."""
    return handle(cntrls.optional,
                  'submit_ce/add_optional_metadata.html',
                  'Add or Edit Metadata', submission_id, flow_controlled=True)


@UI.route('/<int:submission_id>/final_preview', methods=['GET', 'POST'])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control()
def final_preview(submission_id: int) -> Response:
    """Render step 10, preview."""
    return handle(cntrls.finalize, 'submit_ce/final_preview.html',
                  'Preview and Approve', submission_id, flow_controlled=True)


@UI.route('/<int:submission_id>/confirmation', methods=['GET', 'POST'])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control()
def confirmation(submission_id: int) -> Response:
    """Render the final confirmation page."""
    return handle(cntrls.new.final.confirm, "submit_ce/confirm_submit.html",
                  'Submission Confirmed',
                  submission_id, flow_controlled=True)

# Other workflows.


# Jref is a single controller and not a workflow
@UI.route('/<int:submission_id>/jref', methods=["GET", "POST"])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
def jref(submission_id: Optional[int] = None) -> Response:
    """Render the JREF submission page."""
    return handle(cntrls.jref.jref, 'submit_ce/jref.html',
                  'Add journal reference', submission_id,
                  flow_controlled=False)


@UI.route('/<int:submission_id>/withdraw', methods=["GET", "POST"])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
def withdraw(submission_id: Optional[int] = None) -> Response:
    """Render the withdrawal request page."""
    return handle(cntrls.withdraw.request_withdrawal,
                  'submit_ce/withdraw.html', 'Request withdrawal',
                  submission_id, flow_controlled=False)


@UI.route('/<int:submission_id>/request_cross', methods=["GET", "POST"])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control()
def request_cross(submission_id: Optional[int] = None) -> Response:
    """Render the cross-list request page."""
    return handle(cntrls.cross.request_cross,
                  'submit_ce/request_cross_list.html', 'Request cross-list',
                  submission_id, flow_controlled=True)

@UI.route('/testalerts')
def testalerts() -> Response:
    tc = {}
    request.submission, request.events = util.load_submission(1)
    wfp = get_workflow(request.submission)
    request.workflow = wfp
    request.current_stage = wfp.current_stage()
    request.this_stage = wfp.workflow[endpoint_name()]

    tc['workflow'] = wfp
    tc['submission_id'] = 1

    add_immediate_alert(tc, 'WARNING', 'This is a warning to you from the normal submission alert system.', "SUBMISSION ALERT TITLE")
    alerts.flash_failure('This is one of those alerts from base alert(): you failed', 'BASE ALERT')
    return make_response(render_template('submit/testalerts.html', **tc), 200)


@UI.app_template_filter()
def endorsetype(endorsements: List[str]) -> str:
    """
    Transmit endorsement status to template for message filtering.

    Parameters
    ----------
    endorsements : list
        The list of categories (str IDs) for which the user is endorsed.

    Returns
    -------
    str
        For now.

    """
    if len(endorsements) == 0:
        return 'None'
    elif '*.*' in endorsements:
        return 'All'
    return 'Some'
