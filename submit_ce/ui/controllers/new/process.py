"""Controllers for process-related requests, ex. compile PDF."""

import io
from http import HTTPStatus as status
from typing import Tuple, Dict, Any
import logging
from flask import current_app
from arxiv.base import alerts
from arxiv.forms import csrf
from markupsafe import Markup

from submit_ce.domain.event.process import StartCompileSource
from submit_ce.domain.exceptions import SaveError
from submit_ce.api.file_store import SubmissionFileStore
from submit_ce.ui import SUPPORT

from ...auth import user_and_client_from_session
from submit_ce.domain.event import ConfirmSourceProcessed
from arxiv.auth.domain import Session
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError, MethodNotAllowed
from wtforms import SelectField

from ..util import validate_command
from submit_ce.ui.routes.flow_control import ready_for_next, stay_on_this_stage
from submit_ce.ui.backend import get_submission


logger = logging.getLogger(__name__)

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103


def file_process(method: str, params: MultiDict, session: Session,
                 submission_id: str, token: str, **kwargs: Any) -> Response:
    """
    Process the file compilation project.

    Parameters
    ----------
    method : str
        ``GET`` or ``POST``
    session : :class:`Session`
        The authenticated session for the request.
    submission_id : str
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
        else:
            start_compilation(params, session, submission_id, token)
            return compile_status(params, session, submission_id, token)
    raise MethodNotAllowed('Unsupported request')


def _check_status(params: MultiDict, session: Session,  submission_id: str,
                  token: str, **kwargs: Any) -> Response:
    """
    Check for cases in which the preview already exists.

    This will catch cases like PDF-only and others that require no further compilation.
    """
    submitter, client = user_and_client_from_session(session)
    submission, _ = get_submission(submission_id)

    if not submission.is_source_processed:
        form = CompilationForm(params)  # Providing CSRF protection.
        if not form.validate():
            return stay_on_this_stage(({'form': form}, status.OK, {}))

        # TODO rename this SourceProcessedCompleted() Confirm is ambiguous with the user confirming
        command = ConfirmSourceProcessed(creator=submitter, client=client)
        try:
            submission, _ = current_app.api.save(command, submission_id=submission_id)
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


def compile_status(params: MultiDict, session: Session, submission_id: str,
                   token: str, **kwargs: Any) -> Response:
    """
    Returns the status of a compilation.

    Parameters
    ----------
    session : :class:`Session`
        The authenticated session for the request.
    submission_id : str
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
    submission, _ = get_submission(submission_id)
    form = CompilationForm()
    response_data = {
        'submission_id': submission_id,
        'submission': submission,
        'form': form,
        'status': None,
    }

    file_store: SubmissionFileStore = current_app.api.get_file_store()
    file = file_store.get_preview(str(submission_id))
    if file and file.exists():
        response_data['status']="succeeded"

    # Determine whether the current state of the uploaded source content has been compiled.
    #
    # result: Optional[process_source.CheckResult] = None
    # try:
    #     result = process_source.check(submission, submitter, client, token)
    # except process_source.NoProcessToCheck as e:
    #     pass
    # except process_source.FailedToCheckStatus as e:
    #     logger.error('Failed to check status: %s', e)
    #     alerts.flash_failure(Markup(
    #         'There was a problem carrying out your request. Please try'
    #         f' again. {SUPPORT}'
    #     ))
    # if result is not None:
    #     response_data['status'] = result.status
    #     response_data.update(**result.extra)
    return stay_on_this_stage((response_data, status.OK, {}))


def start_compilation(params: MultiDict, session: Session, submission_id: str,
                      token: str, **kwargs: Any) -> Response:
    submitter, client = user_and_client_from_session(session)
    submission, submission_events = get_submission(submission_id)
    form = CompilationForm(params)
    response_data = {
        'submission_id': submission_id,
        'submission': submission,
        'form': form,
        'status': None,
    }

    if not form.validate():
        return stay_on_this_stage((response_data, status.OK, {}))

    command = StartCompileSource(creator=submitter,
                                 client=client,
                                 source_content_id="BOGUS")

    if validate_command(form, command, submission):
        try:
            current_app.api.save(command, submission_id=submission.submission_id)  # The api implementation will call CompileSource.execute()
        except SaveError as e:
            alerts.flash_failure(f"We couldn't process your submission. {SUPPORT}", title="Processing failed")
            raise InternalServerError(response_data) from e

    # try:
    #     result = process_source.start(submission, submitter, client, token)
    # except process_source.FailedToStart as e:
    #     alerts.flash_failure(f"We couldn't process your submission. {SUPPORT}", title="Processing failed")
    #     logger.error('Error while requesting compilation for %s: %s', submission_id, e)
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
    #         alerts.flash_failure(f"Processing failed")
    # else:
    #     alerts.flash_success(SUCCESS_MARKUP, title="Processing started"
    #     )
    #
    #

# TODO move file_preview to its own controller
def file_preview(params, session: Session, submission_id: str, token: str,
                 **kwargs: Any) -> Tuple[io.BytesIO, int, Dict[str, str]]:
    """Serve the PDF preview for a submission."""
    submitter, client = user_and_client_from_session(session)
    submission, submission_events = get_submission(submission_id)
    fstore = current_app.api.get_file_store()
    stream = fstore.get_preview(submission.submission_id)
    pdf_checksum = fstore.get_preview_checksum(submission.submission_id)
    headers = {'Content-Type': 'application/pdf', 'ETag': pdf_checksum}
    return stream, status.OK, headers


def compilation_log(params, session: Session, submission_id: str, token: str,
                    **kwargs: Any) -> Response:
    submitter, client = user_and_client_from_session(session)
    submission, submission_events = get_submission(submission_id)

    NotImplementedError()
    # try:
    #     log = Compiler.get_log(submission.source_content.identifier, checksum,
    #                            token)
    #     headers = {'Content-Type': log.content_type, 'ETag': checksum}
    #     return log.stream, status.OK, headers
    # except exceptions.NotFound:
    #     raise NotFound("No log output produced")


class CompilationForm(csrf.CSRFForm):
    """Generate form to process compilation."""

    PDFLATEX = 'pdflatex'
    COMPILERS = [
        (PDFLATEX, 'PDFLaTeX')
    ]

    compiler = SelectField('Compiler', choices=COMPILERS, default=PDFLATEX)


SUCCESS_MARKUP = \
    Markup("We are processing your submission. This may take a minute or two." \
            " This page will refresh automatically every 5 seconds. You can " \
            " also refresh this page manually to check the current status. ")
TEX_PRODUCED_MARKUP = \
    Markup("The submission PDF file appears to have been produced by TeX. " \
           "<p>This file has been rejected as part your submission because " \
           "it appears to be pdf generated from TeX/LaTeX source. " \
           "For the reasons outlined at in the Why TeX FAQ we insist on " \
           "submission of the TeX source rather than the processed " \
           "version.</p><p>Our software includes an automatic TeX " \
           "processing script that will produce PDF, PostScript and " \
           "dvi from your TeX source. If our determination that your " \
           "submission is TeX produced is incorrect, you should send " \
           "e-mail with your submission ID to " \
           '<a href="mailto:help@arxiv.org">arXiv administrators.</a></p>')
DOCKER_ERROR_MARKUOP = \
    Markup("Our automatic TeX processing system has failed to launch. " \
           "There is a good chance we are aware of the issue, but if the " \
           "problem persists you should send e-mail with your submission " \
           'number to <a href="mailto:help@arxiv.org">arXiv administrators.</a></p>')
