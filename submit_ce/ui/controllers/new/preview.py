"""Controller for serving the compiled PDF preview for a submission.

The single entry point :func:`file_preview` is wired to the
``/<submission_id>/preview.pdf`` route. It serves the compiled PDF (or
raises a friendly 404 when the PDF doesn't exist yet) and fires a
``ConfirmPreview`` event so the submitter is treated as having
reviewed the PDF (this is the 2.0 analog of Submit 1.5's "set
``viewed=1`` when the user opens ``/submit/<id>/view``" behavior).
"""

import io
import logging
from http import HTTPStatus as status
from typing import Tuple, Dict, Any

from flask import current_app
from arxiv.auth.domain import Session
from arxiv.files import FileDoesNotExist
from werkzeug.exceptions import NotFound

from submit_ce.domain.event import ConfirmPreview
from submit_ce.ui.backend import get_submission

from ...auth import user_and_client_from_session


logger = logging.getLogger(__name__)


def file_preview(params, session: Session, submission_id: str, token: str,
                 **kwargs: Any) -> Tuple[io.BytesIO, int, Dict[str, str]]:
    """Serve the PDF preview for a submission.

    Raises
    ------
    werkzeug.exceptions.NotFound
        If no preview PDF exists for this submission yet (e.g., the
        Process step has not run, compilation failed, or the bucket has
        no PDF for any other reason). Flask renders this as a 404
        response so the route can redirect to a friendly HTML page,
        instead of the raw ``Exception("File does not exist")`` that
        :class:`arxiv.files.FileDoesNotExist` would otherwise raise
        when the route tries to ``open()`` the missing file.

    Side effect: when a PDF is served and the submitter has not yet
    confirmed it, dispatch a ``ConfirmPreview`` event so the submitter
    is treated as having reviewed the PDF. This mirrors legacy Submit
    1.x behavior where opening the PDF marked ``viewed=1`` on the
    submission row, enabling the Submit button on the Confirm page
    after a refresh. The event's own validator handles the
    source-format branching (strict checksum check for TeX/PostScript;
    lenient pass for PDF/HTML where the source IS the preview).
    """
    submitter, client = user_and_client_from_session(session)
    submission, submission_events = get_submission(submission_id)
    fstore = current_app.api.get_file_store()

    # Check first that a preview PDF actually exists. Without this, the
    # downstream ``send_file(stream.open('rb'), ...)`` in the route raises
    # a generic Exception and the user sees a 500 stack trace in the new
    # tab. Common causes: the Process step hasn't yet produced a PDF, a
    # transient GCS issue, or the submitter manually navigated here. The
    # route catches NotFound and 302s to a friendly placeholder page.
    stream = fstore.get_preview(submission.submission_id)
    if isinstance(stream, FileDoesNotExist) or not stream.exists():
        logger.info(
            "PDF preview requested but not available for submission %s",
            submission.submission_id,
        )
        raise NotFound(
            "The PDF preview is not yet available. Please return to the "
            "Process step, wait for compilation to finish, and try again. "
            "If processing failed, you may need to fix your source files "
            "and reprocess."
        )

    pdf_checksum = fstore.get_preview_checksum(submission.submission_id)

    # Fire ConfirmPreview if not already confirmed. ConfirmPreview's
    # validator handles both source-format cases:
    #   - TeX/PostScript: requires submission.preview populated by the
    #     Process step's ConfirmSourceProcessed event, and the checksum
    #     must match what we're about to serve.
    #   - PDF/HTML and other non-processing formats: the source IS the
    #     preview, so submission.preview may legitimately be None.
    # We just dispatch the event and let validate() decide; the previous
    # self-heal that fired a bogus ConfirmSourceProcessed with placeholder
    # values is no longer needed (removed in SUBMISSION-167).
    needs_confirm = (
        bool(pdf_checksum)
        and not submission.submitter_confirmed_preview
    )
    logger.info(
        "file_preview: submission=%s pdf_checksum=%r confirmed_preview=%s "
        "needs_confirm=%s",
        submission.submission_id, pdf_checksum,
        submission.submitter_confirmed_preview, needs_confirm,
    )

    if needs_confirm:
        try:
            current_app.api.save(
                ConfirmPreview(creator=submitter, client=client,
                               preview_checksum=pdf_checksum),
                submission_id=submission.submission_id,
            )
            logger.info(
                "file_preview: ConfirmPreview saved for submission %s",
                submission.submission_id,
            )
        except Exception as exc:
            # Don't silently swallow. The PDF still streams to the browser
            # via the return below, but logging at ERROR with stack trace
            # makes the failure obvious in the server console.
            logger.exception(
                "ConfirmPreview save failed for submission %s: %s",
                submission.submission_id, exc,
            )

    headers = {'Content-Type': 'application/pdf', 'ETag': pdf_checksum}
    return stream, status.OK, headers
