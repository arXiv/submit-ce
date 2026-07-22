"""Controllers for process-related requests, ex. compile PDF."""

from http import HTTPStatus as status
from typing import Tuple, Dict, Any
import logging
from flask import current_app
from arxiv.base import alerts
from arxiv.forms import csrf
from markupsafe import Markup

from submit_ce.domain.event.process import StartCompileSource
from submit_ce.domain.exceptions import InvalidEvent, SaveError
from submit_ce.domain.uploads import SourceFormat
from submit_ce.api.file_store import SubmissionFileStore
from submit_ce.ui import SUPPORT

from ...auth import user_and_client_from_session
from submit_ce.domain.event import ConfirmSourceProcessed
from submit_ce.domain.event.process import InstallPdfPreview
from arxiv.auth.domain import Session
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError, MethodNotAllowed
from wtforms import SelectField

from ..util import validate_command
from submit_ce.ui.routes.flow_control import (
    ready_for_next, stay_on_this_stage, advance_to_current,
)
from submit_ce.ui.workflow import conditions
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
    submission, _ = get_submission(submission_id)
    if submission.source_format == SourceFormat.PDF:
        # PDF-only submissions have no compile step. Install the uploaded
        # PDF into the canonical preview slot (mirroring Submit 1.5's
        # Source->process() promoting the PDF to <filepath>.pdf) so the
        # submitter can review it on the Confirm page, then advance.
        _install_pdf_only_preview(str(submission_id), session)
        return advance_to_current(({}, status.OK, {}))

    if method == "GET":
        _maybe_autocompile(params, session, submission_id, token)
        return compile_status(params, session, submission_id, token)
    elif method == "POST":
        if params.get('action') in ['previous', 'next', 'save_exit']:
            return _check_status(params, session, submission_id, token)
        else:
            start_compilation(params, session, submission_id, token)
            current_app.api.get_file_store().uncompress_compile_tarball(submission_id)
            return compile_status(params, session, submission_id, token)
    raise MethodNotAllowed('Unsupported request')


def _install_pdf_only_preview(submission_id: str, session: Session) -> None:
    """Install a PDF-only submission's PDF as its stamped preview.

    Dispatches :class:`.InstallPdfPreview`, whose ``execute()`` runs under
    ``SubmitApi.save``'s submission row lock (see the critical-section note in
    ``CLAUDE.md``): it stamps the uploaded PDF with the temporary submission
    watermark and writes the stamped PDF -- or the unstamped fallback if
    stamping fails -- to the preview slot ``<id>.pdf``. Without this the
    preview slot stays empty, ``/preview.pdf`` 404s, ``ConfirmPreview`` never
    fires, and the Confirm page's Submit button stays disabled.

    Idempotent: no-ops once a preview already exists (e.g., on repeat visits
    to this stage).
    """
    file_store: SubmissionFileStore = current_app.api.get_file_store()
    if file_store.does_preview_exist(submission_id):
        return

    submitter, client = user_and_client_from_session(session)
    try:
        current_app.api.save(
            InstallPdfPreview(creator=submitter, client=client),
            submission_id=submission_id,
        )
    except InvalidEvent as e:
        # Precondition failed under the lock (e.g. not exactly one PDF in the
        # workspace). Unreachable in normal PDF-only flow; log and skip rather
        # than 500 -- the empty preview slot keeps Submit disabled. [SUBMISSION-196]
        logger.warning('Skipped PDF-only preview install for %s: %s',
                       submission_id, e)
        return
    except SaveError as e:
        logger.error('Failed to install PDF-only preview for %s: %s',
                     submission_id, e)
        raise InternalServerError('Could not install PDF preview') from e
    logger.info('Installed PDF-only preview for submission %s', submission_id)


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


def _maybe_autocompile(params: MultiDict, session: Session, submission_id: str,
                       token: str) -> None:
    """Compile the source on arrival at the Process page, only when needed.

    Implements SUBMISSION-75: the submitter no longer has to click "Process
    submission files" to start compilation. On GET we initiate a compile when
    the source is (La)TeX and there is no current compile to reuse, and we skip
    it otherwise so revisiting the page (or refreshing) doesn't burn compute.

    Compilation is (re)triggered when *both*:

    * no valid preview exists -- either nothing has been compiled yet, or the
      previous preview was invalidated by a file change (see
      ``_common_file_change_execute``); and
    * no compile has already been attempted against the current source
      (:func:`conditions.has_compiled_current_source`). This guards the failure
      case: a compile that failed on TeX errors leaves no preview, but its
      ``StartCompileSource`` event means we must *not* silently recompile the
      same broken source on every refresh -- the submitter sees the failure and
      retries via the Reprocess button (a POST).

    Only TeX source is auto-compiled here; PDF-only is handled earlier in
    :func:`file_process`, and non-processing formats (e.g. HTML) need no
    compile. The compile is dispatched as a server-initiated event rather than
    through :func:`start_compilation` because the latter requires a CSRF token
    that a GET request does not carry.

    A failure to reach the compile service is logged and flashed but not raised:
    the page still renders (with no preview), and a manual refresh or Reprocess
    retries -- better than 500-ing on arrival.
    """
    submission, events = get_submission(submission_id)
    if submission.source_format != SourceFormat.TEX:
        return

    file_store: SubmissionFileStore = current_app.api.get_file_store()
    if file_store.does_preview_exist(str(submission_id)):
        return  # A current compile already exists; reuse it.
    if conditions.has_compiled_current_source(submission, events):
        return  # Already attempted for this source (e.g. it failed); don't loop.

    submitter, client = user_and_client_from_session(session)
    command = StartCompileSource(creator=submitter, client=client,
                                 source_content_id="BOGUS")
    try:
        current_app.api.save(command, submission_id=submission_id)
        file_store.uncompress_compile_tarball(submission_id)
    except InvalidEvent as e:
        # Precondition failed under the lock (e.g. empty source). Nothing to
        # compile; leave the page to render its not-started state.
        logger.info('Skipped auto-compile for %s: %s', submission_id, e)
    except SaveError as e:
        logger.error('Auto-compile failed for %s: %s', submission_id, e)
        alerts.flash_failure(
            f"We couldn't process your submission automatically. Use the"
            f" Process button to try again. {SUPPORT}",
            title="Processing failed")


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

    # Show the compile log whenever one exists. Any source file change deletes
    # it (see `_common_file_change_execute`), so a log that is present is always
    # current -- this surfaces the compiler summary on a successful compile and
    # the errors on a failed one, while a stale log from a since-changed source
    # can't appear because it has been removed. (Note we must not gate this on
    # the request-cached event history: `_maybe_autocompile` records the compile
    # event within this same GET, but `get_submission` caches the pre-compile
    # snapshot in `g`, so an event-based check would wrongly hide a just-created
    # current log until the next refresh.) [SUBMISSION-75]
    log = file_store.get_compile_log(str(submission_id))
    if log and log.exists():
        response_data['compile_log'] = log.download_as_text()

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

    # TODO not clear where source_content_id should come from
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
    #         alerts.flash_failure(DOCKER_ERROR_MARKUP)
    #     else:
    #         alerts.flash_failure(f"Processing failed")
    # else:
    #     alerts.flash_success(SUCCESS_MARKUP, title="Processing started"
    #     )
    #
    #

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
DOCKER_ERROR_MARKUP = \
    Markup("Our automatic TeX processing system has failed to launch. " \
           "There is a good chance we are aware of the issue, but if the " \
           "problem persists you should send e-mail with your submission " \
           'number to <a href="mailto:help@arxiv.org">arXiv administrators.</a></p>')
