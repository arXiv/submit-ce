"""Controllers for serving a submission's preview.

:func:`file_preview` is wired to the ``/<submission_id>/preview.pdf`` route.
It serves the compiled PDF (or raises a friendly 404 when the PDF doesn't
exist yet) and fires a ``ConfirmPreview`` event so the submitter is treated
as having reviewed the PDF (this is the 2.0 analog of Submit 1.5's "set
``viewed=1`` when the user opens ``/submit/<id>/view``" behavior).

:func:`html_preview_index` and :func:`html_preview` do the same for HTML
submissions under ``/<submission_id>/preview/html/``, whose source files
are the preview. [SUBMISSION-127]
"""

import io
import logging
import mimetypes
from datetime import datetime, timezone
from http import HTTPStatus as status
from typing import Tuple, Dict, Any, List, Optional

from flask import current_app, render_template, url_for
from arxiv.auth.domain import Session
from arxiv.files import FileDoesNotExist
from arxiv.formats.html import post_process_html, pre_process_html
from arxiv.identifier import Identifier
from arxiv.taxonomy.definitions import CATEGORIES
from werkzeug.exceptions import NotFound

from submit_ce.domain.event import ConfirmPreview
from submit_ce.domain.exceptions import NoSuchDocument
from submit_ce.domain.uploads import SourceFormat, Workspace
from submit_ce.ui.backend import get_submission
from submit_ce.ui.config import settings

from ...auth import is_owner, user_and_client_from_session


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
    # Only the submitter viewing it counts, not an admin.
    needs_confirm = (
        bool(pdf_checksum)
        and not submission.submitter_confirmed_preview
        and is_owner(session, submission_id)
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


def _listing(arxiv_id: Identifier, include_abstract: bool) -> Optional[str]:
    try:
        document = current_app.api.get_document(arxiv_id.id)
    except NoSuchDocument:
        return None
    except Exception:
        logger.exception("Could not load %s for an HTML preview listing", arxiv_id.idv)
        return None
    if arxiv_id.has_version:
        metadata = next((md for md in document.metadata
                         if md.version == arxiv_id.version), None)
    else:
        metadata = document.current_metadata
    if metadata is None:
        return None
    subjects = '; '.join(f'{CATEGORIES[c].full_name} ({c})' if c in CATEGORIES else c
                         for c in (metadata.categories or '').split())
    return render_template('submit/html_preview_listing.html',
                           paper_id=arxiv_id.idv, metadata=metadata,
                           subjects=subjects, include_abstract=include_abstract,
                           abs_url=f'https://{settings.BASE_SERVER}/abs/{arxiv_id.idv}') + '\n'


def html_pages(workspace: Optional[Workspace]) -> List[str]:
    """The paths of an HTML submission's pages, as preflight finds them."""
    if workspace is None:
        return []
    return sorted(f.path for f in workspace.files
                  if not f.ancillary and f.name.lower().endswith('.html'))


def html_preview_index(params, session: Session, submission_id: str, token: str,
                       **kwargs: Any) -> Tuple[Dict[str, Any], int, Dict[str, str]]:
    """List the pages of an HTML submission."""
    submission, _ = get_submission(submission_id)
    if submission.source_format != SourceFormat.HTML:
        raise NotFound("This submission has no HTML preview.")
    workspace = current_app.api.get_file_store().get_workspace(submission_id)
    pages = html_pages(workspace)
    if not pages:
        raise NotFound("This submission has no HTML pages.")
    return {'submission_id': submission_id, 'pages': pages}, status.OK, {}


def html_preview(params, session: Session, submission_id: str, token: str,
                 path: str, **kwargs: Any) -> Tuple[bytes, int, Dict[str, str]]:
    """Serve one source file of an HTML submission.

    Pages are preprocessed as legacy's ``/submit/<id>/view`` did, and the
    submitter opening one fires ``ConfirmPreview`` like :func:`file_preview`.
    Other files, such as images and stylesheets, are served unchanged.
    """
    submitter, client = user_and_client_from_session(session)
    submission, _ = get_submission(submission_id)
    if submission.source_format != SourceFormat.HTML:
        raise NotFound("This submission has no HTML preview.")
    try:
        source = current_app.api.get_file_store().get_source_file(submission_id, path)
    except RuntimeError as exc:  # the store refuses paths outside the submission
        raise NotFound(f"No file {path} in this submission.") from exc
    if isinstance(source, FileDoesNotExist) or not source.exists():
        raise NotFound(f"No file {path} in this submission.")
    with source.open('rb') as stream:
        data = stream.read()

    if not path.lower().endswith('.html'):
        content_type = mimetypes.guess_type(path)[0] or 'application/octet-stream'
        return data, status.OK, {'Content-Type': content_type}

    base_url = url_for('ui.html_preview_index', submission_id=submission_id,
                       _external=True)
    now = datetime.now(timezone.utc)
    stamp = (f'<a href="{base_url}">arXiv:submit/{submission_id}</a>'
             f'  {now:%d %b %Y}')
    data = pre_process_html(data, base_url, stamp, settings.BASE_SERVER)
    search_url = f'https://{settings.BASE_SERVER}/search/'
    data = b''.join(post_process_html(line, _listing, search_url)
                    for line in data.splitlines(keepends=True))

    # Only the submitter viewing it counts, not an admin or moderator.
    if (not submission.submitter_confirmed_preview and not submission.is_finalized
            and is_owner(session, submission_id)):
        try:
            current_app.api.save(ConfirmPreview(creator=submitter, client=client),
                                 submission_id=submission.submission_id)
        except Exception as exc:
            logger.exception("ConfirmPreview save failed for submission %s: %s",
                             submission.submission_id, exc)
    return data, status.OK, {'Content-Type': 'text/html; charset=utf-8'}
