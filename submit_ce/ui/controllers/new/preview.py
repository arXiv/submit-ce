"""Controller for serving the compiled PDF preview for a submission."""

import io
from http import HTTPStatus as status
from typing import Tuple, Dict, Any

from flask import current_app
from arxiv.auth.domain import Session

from ...auth import user_and_client_from_session
from submit_ce.ui.backend import get_submission


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
