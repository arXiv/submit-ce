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
import re
from datetime import datetime, timezone
from http import HTTPStatus as status
from typing import Tuple, Dict, Any, List, Optional
from urllib.parse import quote

from flask import current_app, render_template, url_for
from arxiv.auth.domain import Session
from arxiv.files import FileDoesNotExist
from arxiv.identifier import Identifier, IdentifierException
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


def preprocess_html(html: bytes, base_url: str, stamp: str, link_site: str) -> bytes:
    """Port of legacy ``arXiv::HTML::src2html::pre_process_html`` (arxiv-lib).

    Points old arXiv hosts at ``link_site``, swaps any user ``<base>`` for
    ``base_url``, inserts the stamp, and makes absolute ``src``/``href`` paths
    relative so they resolve inside the submission. Like legacy, it works on
    the raw bytes with regular expressions and leaves scripts alone.
    """
    base = f'<base href="{base_url}" />'.encode()
    stamp_tag = f'<address><p>{stamp}</p></address>'.encode()
    html = re.sub(rb'xxx\.lanl\.gov|arxiv\.org', link_site.encode(), html, flags=re.I)
    html = re.sub(rb'<base\s+href=[^>]*>', b'', html, count=1, flags=re.I | re.S)
    html = _insert_after([rb'<head>', rb'</title>', rb'<html>'], base, html)
    html = _insert_after([rb'<body[^>]*>', rb'</head>', rb'</title>', rb'<html>'],
                         stamp_tag, html)
    for attr in (b'src', b'href'):
        for pattern in (attr + rb'\s*=\s*"/(\S+)"', attr + rb'\s*=\s*/(\S+)'):
            count = 1
            while count:
                html, count = re.subn(pattern, attr + rb'="\1"', html, flags=re.I | re.S)
    return html


_LIST_LINE = re.compile(
    rb'(LIST|ABS):(?:arXiv:)?([a-z-]+(?:\.[A-Z][A-Z])?/\d{7}|\d{4}\.\d{4,5})(v\d+)?', re.I)
_REPORT_NO_LINE = re.compile(rb'\s*REPORT-NO:([A-Za-z0-9-/]+)', re.I)


def postprocess_html(html: bytes, link_site: str) -> bytes:
    """Port of legacy ``src2html::post_process_html``, as arxiv-browse has it.

    A line starting ``LIST:<id>`` or ``ABS:<id>`` becomes that paper's
    listing, with its abstract for ``ABS``. A line starting ``REPORT-NO:<number>``
    becomes a link to the report-number search. Conference indexes list their
    papers this way (arxiv-docs ``help/submit_index``).
    """
    return b''.join(_postprocess_line(line, link_site)
                    for line in html.splitlines(keepends=True))


def _postprocess_line(line: bytes, link_site: str) -> bytes:
    if match := _LIST_LINE.match(line):
        paper_id, version = match.group(2).decode(), (match.group(3) or b'').decode()
        return _listing(paper_id, version, match.group(1).upper() == b'ABS', link_site).encode()
    if match := _REPORT_NO_LINE.match(line):
        number = match.group(1).decode()
        return (f'<a href="https://{link_site}/search/?searchtype=report_num'
                f'&query={quote(number, safe="")}">{number}</a>\n').encode()
    return line


def _listing(paper_id: str, version: str, include_abstract: bool, link_site: str) -> str:
    try:
        document = current_app.api.get_document(Identifier(paper_id).id)
    except (IdentifierException, NoSuchDocument):
        document = None
    except Exception:
        logger.exception("Could not load %s for an HTML preview listing", paper_id)
        document = None
    if document is None:
        metadata = None
    elif version:
        metadata = next((md for md in document.metadata
                         if md.version == int(version[1:])), None)
    else:
        metadata = document.current_metadata
    if metadata is None:
        return f'<dl>\n<dd>{paper_id}{version} [failed to get metadata for paper]</dd>\n</dl>\n'
    subjects = '; '.join(f'{CATEGORIES[c].full_name} ({c})' if c in CATEGORIES else c
                         for c in (metadata.categories or '').split())
    return render_template('submit/html_preview_listing.html',
                           paper_id=paper_id + version, metadata=metadata,
                           subjects=subjects, include_abstract=include_abstract,
                           abs_url=f'https://{link_site}/abs/{paper_id}{version}') + '\n'


def _insert_after(patterns: List[bytes], insert: bytes, html: bytes) -> bytes:
    """Insert after the first pattern that matches, else at the top."""
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.I | re.S)
        if match:
            return html[:match.end()] + insert + html[match.end():]
    return insert + b'\n' + html


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

    Pages are preprocessed as legacy's ``/submit/<id>/view`` did, and serving
    one fires ``ConfirmPreview`` like :func:`file_preview`. Other files, such
    as images and stylesheets, are served unchanged.
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
    data = preprocess_html(data, base_url, stamp, settings.BASE_SERVER)
    data = postprocess_html(data, settings.BASE_SERVER)

    if not submission.submitter_confirmed_preview:
        try:
            current_app.api.save(ConfirmPreview(creator=submitter, client=client),
                                 submission_id=submission.submission_id)
        except Exception as exc:
            logger.exception("ConfirmPreview save failed for submission %s: %s",
                             submission.submission_id, exc)
    return data, status.OK, {'Content-Type': 'text/html; charset=utf-8'}
