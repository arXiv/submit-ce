"""
Controllers for process-related requests.

The controllers in this module leverage
:mod:`arxiv.submission.core.process.process_source`, which provides an
high-level API for orchestrating source processing for all supported source
types.
"""

import io
from http import HTTPStatus as status
from typing import Tuple, Dict, Any, Optional

from arxiv.auth.domain import Session
from arxiv.base import logging, alerts
from arxiv.forms import csrf
from markupsafe import Markup

from submit_ce.ui.backend import save
from submit_ce.ui.domain.event import ConfirmSourceProcessed
from flask import url_for
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError, NotFound, MethodNotAllowed
from wtforms import SelectField

from submit_ce.ui.exceptions import SaveError
from .reasons import TEX_PRODUCED_MARKUP, DOCKER_ERROR_MARKUOP, SUCCESS_MARKUP
from submit_ce.ui.controllers.util import user_and_client_from_session
from submit_ce.ui.routes.flow_control import ready_for_next, stay_on_this_stage
from submit_ce.ui.util import load_submission

logger = logging.getLogger(__name__)

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103


SUPPORT = Markup(
    'If you continue to experience problems, please contact'
    ' <a href="mailto:help@arxiv.org"> arXiv support</a>.'
)


def file_process(method: str, params: MultiDict, session: Session,
                 submission_id: int, token: str, **kwargs: Any) -> Response:
    """
    Process the file compilation project.

    Parameters
    ----------
    method : str
        ``GET`` or ``POST``
    session : :class:`Session`
        The authenticated session for the request.
    submission_id : int
        The identifier of the submission for which the upload is being made.
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
    if method == "GET":
        return compile_status(params, session, submission_id, token)
    elif method == "POST":
        if params.get('action') in ['previous', 'next', 'save_exit']:
            return _check_status(params, session, submission_id, token)
            # User is not actually trying to process anything; let flow control
            # in the routes handle the response.
            # TODO there is a chance this will allow the user to go to next stage without processing
            # return ready_for_next({}, status.SEE_OTHER, {})
        else:
            return start_compilation(params, session, submission_id, token)
    raise MethodNotAllowed('Unsupported request')


def _check_status(params: MultiDict, session: Session,  submission_id: int,
                  token: str, **kwargs: Any) -> None:
    """
    Check for cases in which the preview already exists.

    This will catch cases in which the submission is PDF-only, or otherwise
    requires no further compilation.
    """
    submitter, client = user_and_client_from_session(session)
    submission, _ = load_submission(submission_id)

    if not submission.is_source_processed:
        form = CompilationForm(params)  # Providing CSRF protection.
        if not form.validate():
            return stay_on_this_stage(({'form': form}, status.OK, {}))

        command = ConfirmSourceProcessed(creator=submitter, client=client)
        try:
            submission, _ = save(command, submission_id=submission_id)
            return ready_for_next(({}, status.OK, {}))
        except SaveError as e:
            alerts.flash_failure(Markup(
                'There was a problem carrying out your request. Please'
                f' try again. {SUPPORT}'
            ))
            logger.error('Error while saving command %s: %s',
                         command.event_id, e)
            raise InternalServerError('Could not save changes') from e
    else:
        return ready_for_next(({}, status.OK, {}))


def compile_status(params: MultiDict, session: Session, submission_id: int,
                   token: str, **kwargs: Any) -> Response:
    """
    Returns the status of a compilation.

    Parameters
    ----------
    session : :class:`Session`
        The authenticated session for the request.
    submission_id : int
        The identifier of the submission for which the upload is being made.
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
    submitter, client = user_and_client_from_session(session)
    submission, _ = load_submission(submission_id)
    form = CompilationForm()
    response_data = {
        'submission_id': submission_id,
        'submission': submission,
        'form': form,
        'status': None,
    }
    # Determine whether the current state of the uploaded source content has
    # been compiled.

    raise NotImplementedError()
    # result: Optional[process_source.CheckResult] = None
    # try:
    #     result = process_source.check(submission, submitter, client, token)
    # except process_source.NoProcessToCheck:
    #     pass
    # except process_source.FailedToCheckStatus as e:
    #     logger.error('Failed to check status: %s', e)
    #     alerts.flash_failure(Markup(
    #         'There was a problem carrying out your request. Please try'
    #         f' again. {SUPPORT}'
    #     ))
    if result is not None:
        response_data['status'] = result.status
        response_data.update(**result.extra)
    return stay_on_this_stage((response_data, status.OK, {}))


def start_compilation(params: MultiDict, session: Session, submission_id: int,
                      token: str, **kwargs: Any) -> Response:
    submitter, client = user_and_client_from_session(session)
    submission, submission_events = load_submission(submission_id)
    form = CompilationForm(params)
    response_data = {
        'submission_id': submission_id,
        'submission': submission,
        'form': form,
        'status': None,
    }

    if not form.validate():
        return stay_on_this_stage((response_data,status.OK,{}))
    raise NotImplementedError()
    # try:
    #     result = process_source.start(submission, submitter, client, token)
    # except process_source.FailedToStart as e:
    #     alerts.flash_failure(f"We couldn't process your submission. {SUPPORT}",
    #                          title="Processing failed")
    #     logger.error('Error while requesting compilation for %s: %s',
    #                  submission_id, e)
    #     raise InternalServerError(response_data) from e
    #
    # response_data['status'] = result.status
    # response_data.update(**result.extra)
    #
    # if result.status == process_source.FAILED:
    #     if 'reason' in result.extra and "produced from TeX source" in result.extra['reason']:
    #         alerts.flash_failure(TEX_PRODUCED_MARKUP)
    #     elif 'reason' in result.extra and 'docker' in result.extra['reason']:
    #         alerts.flash_failure(DOCKER_ERROR_MARKUOP)
    #     else:
    #         alerts.flash_failure("Processing failed")
    # else:
    #     alerts.flash_success(SUCCESS_MARKUP, title="Processing started"
    #     )
    #
    # return stay_on_this_stage((response_data, status.OK, {}))


def file_preview(params, session: Session, submission_id: int, token: str,
                 **kwargs: Any) -> Tuple[io.BytesIO, int, Dict[str, str]]:
    """Serve the PDF preview for a submission."""
    submitter, client = user_and_client_from_session(session)
    submission, submission_events = load_submission(submission_id)
    raise NotImplementedError()
    # p = PreviewService.current_session()
    # stream, pdf_checksum = p.get(submission.source_content.identifier,
    #                              submission.source_content.checksum,
    #                              token)
    # headers = {'Content-Type': 'application/pdf', 'ETag': pdf_checksum}
    # return stream, status.OK, headers


def compilation_log(params, session: Session, submission_id: int, token: str,
                    **kwargs: Any) -> Response:
    submitter, client = user_and_client_from_session(session)
    submission, submission_events = load_submission(submission_id)
    checksum = params.get('checksum', submission.source_content.checksum)
    raise NotImplementedError()
    # try:
    #     log = Compiler.get_log(submission.source_content.identifier, checksum,
    #                            token)
    #     headers = {'Content-Type': log.content_type, 'ETag': checksum}
    #     return log.stream, status.OK, headers
    # except exceptions.NotFound:
    #     raise NotFound("No log output produced")


def compile(params: MultiDict, session: Session, submission_id: int,
            token: str, **kwargs) -> Response:
    redirect = url_for('ui.file_process', submission_id=submission_id)
    return {}, status.SEE_OTHER, {'Location': redirect}


class CompilationForm(csrf.CSRFForm):
    """Generate form to process compilation."""

    PDFLATEX = 'pdflatex'
    COMPILERS = [
        (PDFLATEX, 'PDFLaTeX')
    ]

    compiler = SelectField('Compiler', choices=COMPILERS,
                           default=PDFLATEX)
