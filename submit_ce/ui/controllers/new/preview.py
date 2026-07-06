"""Controller for serving the compiled PDF preview for a submission.

The single entry point :func:`file_preview` is wired to the
``/<submission_id>/preview.pdf`` route. It serves the compiled PDF (or
raises a friendly 404 when the PDF doesn't exist yet) and fires the
domain events needed to record that the submitter has viewed the
preview.
"""

import io
import logging
from http import HTTPStatus as status
from typing import Tuple, Dict, Any

from flask import current_app
from arxiv.auth.domain import Session
from arxiv.files import FileDoesNotExist
from werkzeug.exceptions import NotFound

from submit_ce.domain.event import ConfirmSourceProcessed, ConfirmPreview
from submit_ce.ui.backend import get_submission

from ...auth import user_and_client_from_session


logger = logging.getLogger(__name__)


def file_preview(params, session: Session, submission_id: str, token: str,
                 **kwargs: Any) -> Tuple[io.BytesIO, int, Dict[str, str]]:
    """Serve the PDF preview for a submission.

    Raises
    ------
    werkzeug.exceptions.NotFound
        If no preview PDF exists for this submission yet (e.g., the Process
        step has not run or compilation has not produced a PDF). Flask
        renders this as a 404 response, which is a much friendlier failure
        mode than the raw ``Exception("File does not exist")`` that
        :class:`arxiv.files.FileDoesNotExist` would otherwise raise when the
        route tries to ``open()`` the missing file.

    Side effect: when the served PDF matches the current submission preview and
    the submitter has not yet confirmed it (or has confirmed a stale checksum),
    fire a ``ConfirmPreview`` event so the submitter is treated as having
    reviewed the PDF. This mirrors legacy Submit 1.x behavior where opening
    the PDF marked ``viewed=1`` on the submission row, which then enables the
    Submit button on the Confirm page after a refresh.
    """
    submitter, client = user_and_client_from_session(session)
    submission, submission_events = get_submission(submission_id)
    fstore = current_app.api.get_file_store()

    # Check first that a preview PDF actually exists. Without this, the
    # downstream ``send_file(stream.open('rb'), ...)`` in the route raises a
    # generic Exception and the user sees a 500 stack trace in the new tab.
    # Common cause: edge case where compilation is not working and submitter
    # has Confirm and Submit page open.
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

    # ---- diagnostic logging ------------------------------------------
    # Verbose INFO logging so the operator can trace exactly what the
    # preview-view side effect did. If you're staring at the server
    # console wondering why the Submit button is still grayed out,
    # these are the lines to grep for.
    preview_set = submission.preview is not None
    preview_ck = submission.preview.preview_checksum if preview_set else None
    logger.info(
        "file_preview: submission=%s pdf_checksum=%r preview_set=%s "
        "preview_checksum=%r confirmed_preview=%s",
        submission.submission_id, pdf_checksum, preview_set, preview_ck,
        submission.submitter_confirmed_preview,
    )

    # Build the list of events to save when the user views the PDF.
    #
    # ConfirmPreview's domain validation requires submission.preview to be
    # set and to match preview_checksum -- otherwise it raises
    # InvalidEvent("Preview not set on submission"). The legacy DB only
    # persists submitter_confirmed_preview (via the `viewed` column); the
    # Preview dataclass itself is not stored. That means reading the
    # submission back with get_submission() after firing
    # ConfirmSourceProcessed loses preview state, and any subsequent
    # ConfirmPreview save would fail validation.
    #
    # Workaround: pass both events to a single save() call. The save loop
    # applies events sequentially with `before = after`, so ConfirmPreview
    # sees the in-memory submission with preview set by
    # ConfirmSourceProcessed and validates cleanly.
    #
    # When to self-heal ConfirmSourceProcessed:
    #   - submission.preview is None (process step not run, hand-copied
    #     PDF, lost domain event), OR
    #   - preview_checksum has drifted (source was reprocessed or replaced
    #     but the old in-memory state is stale).
    # In production this path is rare; logged at WARNING for visibility.
    needs_source_processed = bool(pdf_checksum) and (
        submission.preview is None
        or submission.preview.preview_checksum != pdf_checksum
    )
    needs_confirm = (
        bool(pdf_checksum)
        and not submission.submitter_confirmed_preview
    )
    logger.info(
        "file_preview: needs_source_processed=%s needs_confirm=%s",
        needs_source_processed, needs_confirm,
    )

    events_to_save = []
    if needs_source_processed:
        events_to_save.append(
            ConfirmSourceProcessed(
                creator=submitter,
                client=client,
                source_id=-1,         # unknown for hand-copied PDFs
                source_checksum='',   # unknown for hand-copied PDFs
                preview_checksum=pdf_checksum,
                size_bytes=getattr(stream, 'size', None) or 0,
                added=getattr(stream, 'updated', None),
            )
        )
    if needs_confirm:
        events_to_save.append(
            ConfirmPreview(creator=submitter, client=client,
                           preview_checksum=pdf_checksum)
        )

    if events_to_save:
        try:
            current_app.api.save(
                *events_to_save,
                submission_id=submission.submission_id,
            )
            if needs_source_processed:
                logger.warning(
                    "Self-healed missing/stale ConfirmSourceProcessed for "
                    "submission %s from served PDF (checksum=%s). "
                    "Investigate the upstream Process step.",
                    submission.submission_id, pdf_checksum,
                )
            logger.info(
                "file_preview: saved %d event(s) for submission %s: %s",
                len(events_to_save), submission.submission_id,
                [e.__class__.__name__ for e in events_to_save],
            )
        except Exception as exc:
            # Don't silently swallow. The PDF still streams to the browser
            # via the return below, but logging at ERROR with stack trace
            # makes the failure obvious in the server console.
            logger.exception(
                "PDF-view event save failed for submission %s "
                "(events=%s): %s",
                submission.submission_id,
                [e.__class__.__name__ for e in events_to_save], exc,
            )

    headers = {'Content-Type': 'application/pdf', 'ETag': pdf_checksum}
    return stream, status.OK, headers
