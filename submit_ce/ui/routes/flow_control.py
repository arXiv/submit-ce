"""Handles which UI route to proceeded in submission workflows."""

from http import HTTPStatus as status
from functools import wraps
from typing import Optional, Callable, Union, Dict, Tuple
from typing_extensions import Literal

from flask import request, redirect, url_for, session
from flask import Response as FResponse
from werkzeug import Response as WResponse
from werkzeug.exceptions import BadRequest

from arxiv.base import alerts, logging
from submit_ce.ui.domain import Submission

from submit_ce.ui.workflow import SubmissionWorkflow, ReplacementWorkflow
from submit_ce.ui.workflow.stages import Stage
from submit_ce.ui.workflow.processor import WorkflowProcessor

from submit_ce.ui.controllers.util import Response as CResponse
from submit_ce.ui.util import load_submission


logger = logging.getLogger(__name__)

EXIT = 'ui.create_submission'

PREVIOUS = 'previous'
NEXT = 'next'
SAVE_EXIT = 'save_exit'


FlowDecision = Literal['SHOW_CONTROLLER_RESULT', 'REDIRECT_EXIT',
                       'REDIRECT_PREVIOUS', 'REDIRECT_NEXT',
                       'REDIRECT_PARENT_STAGE', 'REDIRECT_CONFIRMATION']


Response = Union[FResponse, WResponse]

# might need RESHOW_FORM
FlowAction = Literal['prevous','next','save_exit']
FlowResponse = Tuple[FlowAction, Response]

ControllerDesires = Literal['stage_success', 'stage_reshow', 'stage_current', 'stage_parent']
STAGE_SUCCESS: ControllerDesires = 'stage_success'
STAGE_RESHOW: ControllerDesires = 'stage_reshow'
STAGE_CURRENT: ControllerDesires = 'stage_current'
STAGE_PARENT: ControllerDesires = 'stage_parent'

def ready_for_next(response: CResponse) -> CResponse:
    """Mark the result from a controller being ready to move to the
    next stage"""
    response[0].update({'flow_control_from_controller': STAGE_SUCCESS})
    return response


def stay_on_this_stage(response: CResponse) -> CResponse:
    """Mark the result from a controller as should return to the same stage."""
    response[0].update({'flow_control_from_controller': STAGE_RESHOW})
    return response


def advance_to_current(response: CResponse) -> CResponse:
    """Mark the result from a controller as should return to the same stage."""
    response[0].update({'flow_control_from_controller': STAGE_CURRENT})
    return response


def return_to_parent_stage(response: CResponse) -> CResponse:
    """Mark the result from a controller as should return to the parent stage.
    Such as delete_file to the FileUpload stage."""
    response[0].update({'flow_control_from_controller': STAGE_PARENT})
    return response


def get_controllers_desire(data: Dict) -> Optional[ControllerDesires]:
    return data.get('flow_control_from_controller', None)


def endpoint_name() -> Optional[str]:
    """Get workflow compatable endpoint name from request"""
    if request.url_rule is None:
        return None
    endpoint = request.url_rule.endpoint
    if '.' in endpoint:
        _, endpoint = endpoint.split('.', 1)
    return str(endpoint)


def get_seen() -> Dict[str, bool]:
    """Get seen steps from user session."""
    # TODO Fix seen to handle mutlipe submissions at the same time
    return session.get('steps_seen', {})  # type: ignore


def put_seen(seen: Dict[str, bool]) -> None:
    """Put the seen steps into the users session."""
    # TODO Fix seen to handle mutlipe submissions at the same time
    session['steps_seen'] = seen


def get_workflow(submission: Optional[Submission]) -> WorkflowProcessor:
    """Guesses the workflow based on the submission and its version."""
    if submission is not None and submission.version > 1:
        return WorkflowProcessor(ReplacementWorkflow, submission, get_seen())
    return WorkflowProcessor(NewSubmissionWorkflow, submission, get_seen())


def to_stage(stage: Optional[Stage], ident: str) -> Response:
    """Return a flask redirect to Stage."""
    if stage is None:
        return redirect(url_for('ui.create_submission'), code=status.SEE_OTHER)
    loc = url_for(f'ui.{stage.endpoint}', submission_id=ident)
    return redirect(loc, code=status.SEE_OTHER)


def to_previous(wfs: WorkflowProcessor, stage: Stage, ident: str) -> Response:
    """Return a flask redirect to the previous stage."""
    return to_stage(wfs.workflow.previous_stage(stage), ident)


def to_next(wfs: WorkflowProcessor, stage: Stage, ident: str) -> Response:
    """Return a flask redirect to the next stage."""
    if stage is None:
        return to_current(wfs, ident)
    else:
        return to_stage(wfs.next_stage(stage), ident)


def to_current(wfs: WorkflowProcessor, ident: str, flash: bool = True)\
   -> Response:
    """Return a flask redirect to the stage required by the workflow."""
    next_stage = wfs.current_stage()
    if flash and next_stage is not None:
        alerts.flash_warning(f'Please {next_stage.label} before proceeding.')
    return to_stage(next_stage, ident)


# TODO QUESTION: Can we just wrap the controller and not
# do the decorate flask route to wrap the controller?
# Answer: Not sure, @wraps saves the function name which might
# be done for debugging.


def flow_control(blueprint_this_stage: Optional[Stage] = None,
                 exit: str = EXIT) -> Callable:
    """Get a blueprint route decorator that wraps a controller to
    handle redirection to next/previous steps.


    Parameters
    ----------

    blueprint_this_stage :
    The mapping of the Stage to blueprint is in the Stage. So,
    usually, this will be None and the stage will be determined from
    the context by checking the submission and route. If passed, this
    will be used as the stage for controlling the flow of the wrapped
    controller. This will allow a auxilrary route to be used with a
    stage, ex delete_all_files route for the stage FileUpload.

    exit:
    Route to redirect to when user selectes exit action.

    """
    def route(controller: Callable) -> Callable:
        """Decorate blueprint route so that it wrapps the controller with
        workflow redirection."""        
        # controler gets 'updated' to look like wrapper but keeps
        # name and docstr
        # https://docs.python.org/2/library/functools.html#functools.wraps
        @wraps(controller)
        def wrapper(submission_id: str) -> Response:
            """Update the redirect to the next, previous, or exit page."""
            
            action = request.form.get('action', None)
            submission, _ = load_submission(submission_id)
            workflow = request.workflow
            this_stage = blueprint_this_stage or \
                workflow.workflow[endpoint_name()]

            # convert classes, ints and strs to actual instances
            this_stage = workflow.workflow[this_stage]

            if workflow.is_complete() and not endpoint_name() == workflow.workflow.confirmation.endpoint:
                return to_stage(workflow.workflow.confirmation, submission_id)

            if not workflow.can_proceed_to(this_stage):
                logger.debug(f'sub {submission_id} cannot proceed to {this_stage}')
                return to_current(workflow, submission_id)

            # If the user selects "go back", we attempt to save their input
            # above. But if the input does not validate, we don't prevent them
            # from going to the previous step.
            try:
                data, code, headers, resp_fn = controller(submission_id)
                #WARNING: controllers do not update the submission in this scope
            except BadRequest:
                if action == PREVIOUS:
                    return to_previous(workflow, this_stage, submission_id)
                raise

            workflow.mark_seen(this_stage)
            put_seen(workflow.seen)

            last_stage = workflow.workflow.order[-1] == this_stage
            controller_action = get_controllers_desire(data)
            flow_desc = flow_decision(request.method, action, code,
                                      controller_action, last_stage)
            logger.debug(f'method: {request.method} action: {action}, code: {code}, '
                         f'controller action: {controller_action}, last_stage: {last_stage}')
            logger.debug(f'flow decisions is {flow_desc}')

            if flow_desc == 'REDIRECT_CONFIRMATION':
                return to_stage(workflow.workflow.confirmation, submission_id)
            if flow_desc == 'SHOW_CONTROLLER_RESULT':
                return resp_fn()
            if flow_desc == 'REDIRECT_EXIT':
                return redirect(url_for(exit), code=status.SEE_OTHER)
            if flow_desc == 'REDIRECT_NEXT':
                return to_next(workflow, this_stage, submission_id)
            if flow_desc == 'REDIRECT_PREVIOUS':
                return to_previous(workflow, this_stage, submission_id)
            if flow_desc == 'REDIRECT_PARENT_STAGE':
                return to_stage(this_stage, submission_id)
            else:
                raise ValueError(f'flow_desc must be of type FlowDecision but was {flow_desc}')

        return wrapper
    return route


def flow_decision(method: str,
                  user_action: Optional[str],
                  code: int,
                  controller_action: Optional[ControllerDesires],
                  last_stage: bool)\
                  -> FlowDecision:
    # For now with GET we do the same sort of things
    if method == 'GET' and controller_action == STAGE_CURRENT:
        return 'REDIRECT_NEXT'
    if (method == 'GET' and code == 200) or \
       (method == 'GET' and controller_action == STAGE_RESHOW):
        return 'SHOW_CONTROLLER_RESULT'
    if method == 'GET' and code != status.OK:
        return 'SHOW_CONTROLLER_RESULT'  # some sort of error?

    if method != 'POST':
        return 'SHOW_CONTROLLER_RESULT'  # Not sure, HEAD? PUT?

    #  after this point method must be POST
    if controller_action == STAGE_SUCCESS:
        if last_stage:
            return 'REDIRECT_CONFIRMATION'
        if user_action == NEXT:
            return 'REDIRECT_NEXT'
        if user_action == SAVE_EXIT:
            return 'REDIRECT_EXIT'
        if user_action == PREVIOUS:
            return 'REDIRECT_PREVIOUS'
        if user_action is None:  # like cross_list with action ADD?
            return 'SHOW_CONTROLLER_RESULT'

    if controller_action == STAGE_RESHOW:
        if user_action == NEXT:
            # Reshow the form to the due to form errors
            return 'SHOW_CONTROLLER_RESULT'
        if user_action == PREVIOUS:
            # User wants to go back but there are errors on the form
            # We ignore the errors and go back.  The user's form input
            # is probably lost.
            return 'REDIRECT_PREVIOUS'
        if user_action == SAVE_EXIT:
            return 'REDIRECT_EXIT'

    if controller_action == STAGE_PARENT:        
        # This is what we get from a sub-form like upload_delete.delete_file
        # on success. Redirect to parent stage.
        return 'REDIRECT_PARENT_STAGE'

    # These are the same as if the controller_action was STAGE_SUCCESS
    # Not sure if that is a good thing or a bad thing.
    if user_action == NEXT:
        return 'REDIRECT_NEXT'
    if user_action == SAVE_EXIT:
        return 'REDIRECT_EXIT'
    if user_action == PREVIOUS:
        return 'REDIRECT_PREVIOUS'
    # default to what?
    return 'SHOW_CONTROLLER_RESULT'
