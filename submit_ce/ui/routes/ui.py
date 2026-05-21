"""Provides routes for the submission user interface."""

from typing import Optional, Callable, Dict, List, Union, Any

from arxiv.auth.auth import scopes
from arxiv.auth.auth.decorators import scoped
from arxiv.base import logging, alerts
from flask import Blueprint, make_response, redirect, request, render_template, url_for, send_file
from flask import Response as FResponse
from markupsafe import Markup
from werkzeug import Response as WResponse
from werkzeug.datastructures import MultiDict
from submit_ce.ui import controllers as cntrls
from submit_ce.ui.controllers.debug import debug_events
from submit_ce.ui.controllers.new import upload
from submit_ce.ui.controllers.new import review
from submit_ce.ui.controllers.new import upload_delete
from ..auth import is_owner, is_admin_or_dev
from submit_ce.ui.workflow.processor import WorkflowProcessor
from submit_ce.ui.workflow.stages import FileUpload
from .flow_control import flow_control, get_workflow, endpoint_name
from ..backend import get_submission




#from submit_ce.ui import util

logger = logging.getLogger(__name__)

UI = Blueprint('ui', __name__, url_prefix='/')


Response = Union[FResponse, WResponse]


def redirect_to_login(*args, **kwargs) -> Response:
    """Send the unauthorized user to the login page."""
    return redirect(url_for('login'))


@UI.before_request
def load_submission() -> None:
    """Load the submission before the request is processed."""
    if request.view_args is None or 'submission_id' not in request.view_args:
        return
    submission_id = request.view_args['submission_id']
    submission, events = get_submission(submission_id)  # this may throw NotFound
    wfp = get_workflow(submission, events)

    # These should probably be moved to flask.g since reqeust doesn't always work well
    request.submission = submission
    request.events = events
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
           submission_id: Optional[str] = None,
           get_params: bool = False, flow_controlled: bool = False,
           **kwargs: Any) -> Response:
    """
    Generalized request handling pattern.

    Parameters
    ----------
    controller : callable
        A controller function with the signature ``(method: str, params:
        MultiDict, session: Session, submission_id: str, token: str) ->
        Tuple[dict, int, dict]``
    template : str
        HTML template to use in the response.
    title : str
        Page title, if not provided by controller.
    submission_id : str or None
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
    logger.debug('%s %s %s, title %s, and ID %s',
                 controller.__name__, request.method, template, title, submission_id)
    if request.method == 'GET' and get_params:
        request_data = MultiDict(request.args.items(multi=True))
    else:
        request_data = MultiDict(request.form.items(multi=True))

    context = {'pagetitle': title}
    auth = getattr(request, "auth", None)
    # TODO this might be a good place to detect unauth and redirect to login

    data, code, headers = controller(request.method, request_data, auth, submission_id, **kwargs)
    context.update(data)

    if flow_controlled:
        logger.debug('%s flow_controled %s', controller.__name__, code )
        return (data, code, headers,
                lambda: make_response(render_template(template, **context), code))
    if code < 300:
        logger.debug('%s status %s', controller.__name__, code)
        response = make_response(render_template(template, **context), code)
    elif 'Location' in headers:
        logger.debug('%s redirect to %s', controller.__name__, headers['Location'])
        response = redirect(headers['Location'], code=code)
    else:
        logger.debug('%s status %s', controller.__name__, code)
        response = FResponse(response=context, status=code, headers=headers)
    return response


@UI.route('/status', methods=['GET'])
def service_status():
    """Status endpoint."""
    return 'ok'


@UI.route('/', methods=["GET"])
@scoped(scopes.CREATE_SUBMISSION, unauthorized=redirect_to_login)
def manage_submissions():
    """Display the submission management dashboard."""
    return handle(cntrls.manage_submissions, 'submit/manage_submissions.html',
                  'Manage submissions')


@UI.route('/', methods=["POST"])
@scoped(scopes.CREATE_SUBMISSION, unauthorized=redirect_to_login)
def create_submission():
    """Create a new submission."""
    return handle(cntrls.create, 'submit/manage_submissions.html',
                  'Create a new submission')


@UI.route('/<submission_id>/unsubmit', methods=["GET", "POST"])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
def unsubmit_submission(submission_id: str):
    """Unsubmit (unfinalize) a submission."""
    return handle(cntrls.new.unsubmit.unsubmit,
                  'submit/confirm_unsubmit.html',
                  'Unsubmit submission', submission_id)


@UI.route('/<submission_id>/delete', methods=["GET", "POST"])
@scoped(scopes.DELETE_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
def delete_submission(submission_id: str):
    """Delete, or roll a submission back to the last announced state."""
    return handle(cntrls.delete.delete,
                  'submit/confirm_delete_submission.html',
                  'Delete submission or replacement', submission_id)


@UI.route('/<submission_id>/cancel/<string:request_id>', methods=["GET", "POST"])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
def cancel_request(submission_id: str, request_id: str):
    """Cancel a pending request."""
    return handle(cntrls.delete.cancel_request,
                  'submit/confirm_cancel_request.html', 'Cancel request',
                  submission_id, request_id=request_id)


@UI.route('/<submission_id>/replace', methods=["POST"])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
def create_replacement(submission_id: str):
    """Create a replacement submission."""
    return handle(cntrls.new.create.replace, 'submit/replace.html',
                  'Create a new version (replacement)', submission_id)


@UI.route('/<submission_id>', methods=["GET"])
@scoped(scopes.VIEW_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
def submission_status(submission_id: str) -> Response:
    """Display the current state of the submission."""
    return handle(cntrls.submission_status, 'submit/status.html',
                  'Submission status', submission_id)


@UI.route('/<submission_id>/edit', methods=['GET'])
@scoped(scopes.VIEW_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control()
def submission_edit(submission_id: str) -> Response:
    """Redirects to current edit stage of the submission."""
    return handle(cntrls.submission_edit, 'submit/status.html',
                  'Submission status', submission_id, flow_controlled=True)

# # TODO: remove me!!
# @UI.route(path('announce'), methods=["GET"])
# @scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner)
# def announce(submission_id: str) -> Response:
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
# def place_on_hold(submission_id: str) -> Response:
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
# def apply_cross(submission_id: str) -> Response:
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
# def reject_cross(submission_id: str) -> Response:
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
# def apply_withdrawal(submission_id: str) -> Response:
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
# def reject_withdrawal(submission_id: str) -> Response:
#     """WARNING WARNING WARNING this is for testing purposes only."""
#     util.reject_withdrawal(submission_id)
#     target = url_for('ui.submission_status', submission_id=submission_id)
#     return Response(response={}, status=status.SEE_OTHER,
#                     headers={'Location': target})


@UI.route('/<submission_id>/verify_user', methods=['GET', 'POST'])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control()
def verify_user(submission_id: Optional[str] = None) -> Response:
    """Render the submit_ce start page."""
    return handle(cntrls.verify, 'submit/verify_user.html',
                  'Verify User Information', submission_id, flow_controlled=True)


@UI.route('/<submission_id>/policy', methods=['GET', 'POST'])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control()
def policy(submission_id: str) -> Response:
    """Render step 2, policy agreement."""
    return handle(cntrls.policy, 'submit/policy.html',
                  'Acknowledge Policy Statement', submission_id,
                  flow_controlled=True)


@UI.route('/<submission_id>/license', methods=['GET', 'POST'])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control()
def license(submission_id: str) -> Response:
    """Render step 3, select license."""
    return handle(cntrls.license, 'submit/license.html',
                  'Select a License', submission_id, flow_controlled=True)


@UI.route('/<submission_id>/classification', methods=['GET', 'POST'])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control()
def classification(submission_id: str) -> Response:
    """Render step 4, choose classification."""
    return handle(cntrls.classification,
                  'submit/classification.html',
                  'Choose a Primary Classification', submission_id,
                  flow_controlled=True)


@UI.route('/<submission_id>/file_upload', methods=['GET', 'POST'])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control()
def file_upload(submission_id: str) -> Response:
    """Render step 7, file upload."""
    return handle(upload.upload_files, 'submit/file_upload.html',
                  'Upload Files', submission_id, files=request.files,
                  token=request.environ['token'], flow_controlled=True)

@UI.route('/<submission_id>/review_files', methods=['GET', 'POST'])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control()
def review_files(submission_id: str) -> Response:
    """Render step 7b, review files placeholder."""
    return handle(review.review_files, 'submit/review_files.html',
                  'Review Files', submission_id, files=request.files,
                  token=request.environ['token'], flow_controlled=True)

@UI.route('/<submission_id>/file_delete', methods=["GET", "POST"])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control(FileUpload)
def file_delete(submission_id: str) -> Response:
    """Provide the file deletion endpoint, part of the upload step."""
    return handle(upload_delete.delete_file, 'submit/confirm_delete.html',
                  'Delete File', submission_id, get_params=True,
                  token=request.environ['token'], flow_controlled=True)


@UI.route('/<submission_id>/file_delete_all', methods=["GET", "POST"])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control(FileUpload)
def file_delete_all(submission_id: str) -> Response:
    """Provide endpoint to delete all files, part of the upload step."""
    return handle(upload_delete.delete_all,
                  'submit/confirm_delete_all.html', 'Delete All Files',
                  submission_id, get_params=True,
                  token=request.environ['token'], flow_controlled=True)


@UI.route('/<submission_id>/file_process', methods=['GET', 'POST'])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control()
def file_process(submission_id: str) -> Response:
    """Render step 8, file processing."""
    return handle(cntrls.process.file_process, 'submit/file_process.html',
                  'Process Files', submission_id, get_params=True,
                  token=request.environ['token'], flow_controlled=True)


@UI.route('/<submission_id>/preview.pdf', methods=["GET"])
@scoped(scopes.VIEW_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
# TODO @flow_control(Process)?
def file_preview(submission_id: str) -> Response:
    data, code, headers = cntrls.new.process.file_preview(
        MultiDict(request.args.items(multi=True)),
        request.auth,
        submission_id,
        request.environ['token']
    )
    # TODO This needs to have range request handling like arxiv-browse
    rv = send_file(data.open('rb'), mimetype=headers['Content-Type'])
    rv.set_etag(headers['ETag'])
    rv.headers['Content-Length'] = str(data.size)
    rv.headers['Cache-Control'] = 'no-store'
    return rv


@UI.route('/<submission_id>/compilation_log', methods=["GET"])
@scoped(scopes.VIEW_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
# TODO @flow_control(Process) ?
def compilation_log(submission_id: str) -> Response:
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


@UI.route('/<submission_id>/add_metadata', methods=['GET', 'POST'])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control()
def add_metadata(submission_id: str) -> Response:
    """Render step 9, metadata."""
    return handle(cntrls.metadata, 'submit/add_metadata.html',
                  'Add or Edit Metadata', submission_id, flow_controlled=True)


@UI.route('/<submission_id>/final_preview', methods=['GET', 'POST'])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control()
def final_preview(submission_id: str) -> Response:
    """Render step 10, preview."""
    return handle(cntrls.finalize, 'submit/final_preview.html',
                  'Preview and Approve', submission_id, flow_controlled=True)


@UI.route('/<submission_id>/confirmation', methods=['GET', 'POST'])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control()
def confirmation(submission_id: str) -> Response:
    """Render the final confirmation page."""
    return handle(cntrls.new.final.confirm, "submit/confirm_submit.html",
                  'Submission Confirmed',
                  submission_id, flow_controlled=True)

# Other workflows.


# Jref is a single controller and not a workflow
@UI.route('/<submission_id>/jref', methods=["GET", "POST"])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
def jref(submission_id: Optional[str] = None) -> Response:
    """Render the JREF submission page."""
    return handle(cntrls.jref.jref, 'submit/jref.html',
                  'Add journal reference', submission_id,
                  flow_controlled=False)


@UI.route('/<submission_id>/withdraw', methods=["GET", "POST"])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
def withdraw(submission_id: Optional[str] = None) -> Response:
    """Render the withdrawal request page."""
    return handle(cntrls.withdraw.request_withdrawal,
                  'submit/withdraw.html', 'Request withdrawal',
                  submission_id, flow_controlled=False)


@UI.route('/<submission_id>/request_cross', methods=["GET", "POST"])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_owner,
                        unauthorized=redirect_to_login)
@flow_control()
def request_cross(submission_id: Optional[str] = None) -> Response:
    """Render the cross-list request page."""
    return handle(cntrls.cross.request_cross,
                  'submit/request_cross_list.html', 'Request cross-list',
                  submission_id, flow_controlled=True)

@UI.route('/testalerts')
def testalerts() -> Response:
    tc = {}
    request.submission, request.events = get_submission(1)
    wfp = get_workflow(request.submission, request.events)
    request.workflow = wfp
    request.current_stage = wfp.current_stage()
    request.this_stage = wfp.workflow[endpoint_name()]

    tc['workflow'] = wfp
    tc['submission_id'] = 1

    add_immediate_alert(tc, 'WARNING', 'This is a warning to you from the normal submission alert system.', "SUBMISSION ALERT TITLE")
    alerts.flash_failure('This is one of those alerts from base alert(): you failed', 'BASE ALERT')
    return make_response(render_template('submit/testalerts.html', **tc), 200)

@UI.route('/debug/<submission_id>/events', methods=["GET"])
@scoped(scopes.VIEW_SUBMISSION, authorizer=is_admin_or_dev,
        unauthorized=redirect_to_login)
def get_debug_events(submission_id: Optional[str] = None) -> Response:
    return handle(debug_events.debug_events, 'debug/debug_events.html',
                  'Debug Events', submission_id,
                  token=request.environ['token'])


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
