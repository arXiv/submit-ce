"""Controller for the Download Submission Agreement endpoint.

Serves a personalized PDF of the submission agreement, stamped with the
submission ID, submitter name, submission date, license, and agreement_id
that the user accepted on the Agreement step.

This endpoint is invoked from the Confirm page (see final_preview.html) so
the user can retain a copy of the submission agreement they accepted.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from http import HTTPStatus as status
from typing import Any, Dict, Tuple

from arxiv.auth.domain import Session
from werkzeug.datastructures import MultiDict

from submit_ce.ui.auth import user_and_client_from_session
from submit_ce.ui.backend import get_submission


logger = logging.getLogger(__name__)


def _submitter_display_name(submission, session: Session) -> str:
    """Best-effort: prefer submission.creator/owner.name, then session user."""
    for agent in (getattr(submission, "creator", None),
                  getattr(submission, "owner", None)):
        name = getattr(agent, "name", None) if agent else None
        if name:
            return name
    user = getattr(session, "user", None)
    if user:
        for attr in ("name", "username", "email"):
            val = getattr(user, attr, None)
            if val:
                return val
    return "Unknown submitter"


def _license_display(submission) -> str:
    """Return a human-readable label for the chosen license, or '(none)'."""
    lic = getattr(submission, "license", None)
    if not lic:
        return "(no license selected)"
    name = getattr(lic, "name", None)
    uri = getattr(lic, "uri", None)
    if name and uri:
        return f"{name} ({uri})"
    return name or uri or "(unknown)"


def _format_date(value) -> str:
    if value is None:
        return "(unknown)"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S %Z").strip()
    return str(value)


def _build_agreement_pdf(submission, session: Session) -> bytes:
    """Render the personalized submission-agreement PDF and return its bytes.

    Uses reportlab's Platypus high-level API. The agreement body is currently
    placeholder copy that mirrors what the Agreement step shows; replace with
    the canonical legal text once it has been finalized by arXiv legal.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    sample = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "AgrTitle", parent=sample["Title"],
        fontSize=18, leading=22, spaceAfter=14,
        textColor=colors.HexColor("#b31b1b"),
    )
    h2_style = ParagraphStyle(
        "AgrH2", parent=sample["Heading2"],
        fontSize=12, leading=16, spaceBefore=12, spaceAfter=6,
        textColor=colors.HexColor("#1e8bc3"),
    )
    body_style = ParagraphStyle(
        "AgrBody", parent=sample["BodyText"],
        fontSize=10, leading=14, spaceAfter=6,
    )
    small_style = ParagraphStyle(
        "AgrSmall", parent=body_style, fontSize=8.5,
        textColor=colors.HexColor("#666666"),
    )

    submitter_name = _submitter_display_name(submission, session)
    submission_id = getattr(submission, "submission_id", "(unknown)")
    submitted_dt = (getattr(submission, "submitted", None)
                    or getattr(submission, "created", None))
    license_display = _license_display(submission)
    agreement_id = getattr(submission, "agreement_id", None) or "(unknown)"
    generated_at = datetime.now(timezone.utc)

    story = []
    story.append(Paragraph("arXiv Submission Agreement", title_style))
    story.append(Paragraph(
        "This document is a personalized record of the submission agreement "
        "accepted by the submitter at the time of submission.",
        body_style,
    ))

    # ---- Personalized stamp -------------------------------------------------
    story.append(Paragraph("Submission record", h2_style))
    detail_rows = [
        ["Submission ID:", str(submission_id)],
        ["Submitter:",     submitter_name],
        ["Submitted on:",  _format_date(submitted_dt)],
        ["License:",       license_display],
        ["Agreement ID:",  str(agreement_id)],
        ["Generated at:",  _format_date(generated_at)],
    ]
    tbl = Table(detail_rows, colWidths=[1.3 * inch, 5.2 * inch], hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("LEADING", (0, 0), (-1, -1), 12),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
    ]))
    story.append(tbl)

    # ---- Agreement body (placeholder copy for now) --------------------------
    story.append(Paragraph("Agreement", h2_style))
    placeholder_paragraphs = [
        "By accepting this submission agreement, the submitter affirms that "
        "they have the right to make the work available under the license "
        "indicated above, and that the work conforms to arXiv submission "
        "policies including those covering content quality, attribution, "
        "and acceptable subject matter.",

        "Once announced, this version of the submission cannot be amended "
        "except through replacement or withdrawal. Non-core metadata "
        "(journal reference, DOI, MSC or ACM classification, and report "
        "number) may be updated at any time without a new revision.",

        "The license selection is permanent for this version and cannot be "
        "amended after announcement. Any subsequent versions must use a "
        "compatible license.",

        "This document is generated automatically as a record of acceptance "
        "and does not constitute the full text of the arXiv submission "
        "agreement. The canonical agreement text identified by Agreement ID "
        f"{agreement_id} is the authoritative version.",
    ]
    for para in placeholder_paragraphs:
        story.append(Paragraph(para, body_style))

    story.append(Spacer(1, 0.25 * inch))
    story.append(Paragraph(
        "For the canonical agreement text and arXiv policies, see "
        "<font color=\"#1e8bc3\">https://arxiv.org/help/policies</font>. "
        "Questions about this submission record may be directed to "
        "<font color=\"#1e8bc3\">arxiv.org/help/contact</font>.",
        small_style,
    ))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.75 * inch, bottomMargin=0.6 * inch,
        title=f"arXiv Submission Agreement - {submission_id}",
        author=submitter_name,
    )
    doc.build(story)
    return buf.getvalue()


def download_submission_agreement(
    method: str,
    params: MultiDict,
    session: Session,
    submission_id: str,
    **kwargs: Any,
) -> Tuple[io.BytesIO, int, Dict[str, str]]:
    """Return a personalized submission-agreement PDF for the user's records."""
    # Verify the submission exists and is loadable in the current user's scope.
    submission, _ = get_submission(submission_id)
    _ = user_and_client_from_session(session)  # forces auth resolution

    pdf_bytes = _build_agreement_pdf(submission, session)
    stream = io.BytesIO(pdf_bytes)
    stream.seek(0)

    filename = f"arxiv-submission-agreement-{submission_id}.pdf"
    headers = {
        "Content-Type": "application/pdf",
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
    }
    return stream, status.OK, headers
