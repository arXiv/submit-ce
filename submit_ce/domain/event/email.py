"""Events that send email as a side effect.

TODO ``Re:`` resubmit threading
"""
from typing import Optional, TYPE_CHECKING
from urllib.parse import urlparse

from ..agent import System, User
from ..config import SubmitConfig
from ..submission import Submission, SubmissionType
from .base import EventWithSideEffect

if TYPE_CHECKING:
    from submit_ce.api.submit import SubmitApi

import logging
logger = logging.getLogger(__name__)


# Body template for the "new submission" confirmation, from the legacy
# OnSubmit `new` template (submit_email_feature_description.md, "New submission
# body"). The dashboard URL comes from SubmitConfig.
#
# TODO: parameterize the "20:00 ET" schedule text via config

_NEW_SUBMISSION_BODY = """\
Dear {name},

Thank you for submitting your work to arXiv.

Your submission has been received and is under consideration. The temporary submission number is:
{submission_id}.

As with all submissions, this work will go through technical and moderation checks. You will be contacted by arXiv when the work is announced or if any issues are identified.

Our goal is to screen and announce papers as quickly as possible while ensuring that papers meet long-term archival standards. Generally, this process takes two business days, with announcements occurring at 20:00 ET, Sunday through Thursday.

You can make changes and view the current status of the submission from your user dashboard: {dashboard_url}

Below is a copy of the submission information.

Regards,
arXiv Support


{summary}
"""

# TODO: replace placeholder bodies below with real per-type content


def _render_auto_hold_body(
    submission: Submission,
    submission_id: str,
    submit_url: str,
    this_site: str,
    www_admin: str,
    summary: str,
) -> str:
    """Render the auto_hold email body.

    Faithfully translated from ``$tmpl_new_user_auto_hold`` in
    ``arxiv-lib/lib/arXiv/Submit/Email/OnSubmit.pm`` (lines 298-349).
    Conditions are evaluated per flag; only ``is_oversize`` is wired now —
    the remaining four (``multiple``, ``linenos``, ``text_extraction_failure``,
    ``missing_pdf``) will be added when those Submission fields exist.
    """
    # -- Summary block -------------------------------------------------------
    summary_lines: list[str] = []
    if submission.is_oversize:
        summary_lines.append("   Oversize submission")
    # TODO: append for multiple, linenos, text_extraction_failure, missing_pdf

    # -- Detail block --------------------------------------------------------
    detail_parts: list[str] = []
    if submission.is_oversize:
        detail_parts.append(
            f"Oversize submission: Your article is currently in \"on-hold\" status"
            f" because it is over our size limits. It will not be announced without"
            f" action from arXiv administrators either after you correct the"
            f" over-size issue, or if you are given permission because there is a"
            f" good reason for why your paper should be announced as-is (e.g. the"
            f" source of your paper is efficient already, or you have large ancillary"
            f" files). Please see:\n"
            f"\n"
            f"   https://{this_site}/help/sizes\n"
            f"\n"
            f"for a discussion related to arXiv's file size warnings.\n"
            f"\n"
            f"A common problem is large and inefficient postscript files in LaTeX"
            f" submissions. The simplest method to correct this issue is to convert"
            f" any postscript figures into pdf and convert your submission to use"
            f" pdflatex. See:\n"
            f"\n"
            f"   https://{this_site}/help/submit_tex#pdflatex\n"
            f"\n"
            f"for a brief discussion regarding the considerations for using pdflatex."
            f" You may also wish to consider bitmapping complex figures. For a more"
            f" complete discussion see:\n"
            f"\n"
            f"   https://{this_site}/bitmap/index"
        )
    # TODO: append detail paragraphs for multiple, linenos, text_extraction_failure,
    # missing_pdf when those Submission fields exist.

    conditions_summary = "\n".join(summary_lines)
    conditions_detail = "\n\n".join(detail_parts)

    return (
        f"Your submission to arXiv is on hold.\n"
        f"\n"
        f"Your temporary submission identifier is: {submission_id}.\n"
        f"You may update your submission at: {submit_url}\n"
        f"\n"
        f"Your article is currently in \"on-hold\" status because of the conditions"
        f" listed below. Once you have corrected these conditions, please update your"
        f" source files, reprocess/view your submission and submit your article again."
        f" This sequence should automatically move your submission to \"submitted\""
        f" status.\n"
        f"\n"
        f"Summary:\n"
        f"\n"
        f"{conditions_summary}\n"
        f"\n"
        f"Additional details on each of these conditions are included below:\n"
        f"\n"
        f"{conditions_detail}\n"
        f"\n"
        f"You may resubmit your paper once you have addressed all the issues listed"
        f" above. If you are not able to resolve these matters, or feel you are"
        f" receiving this warning in error, please contact {www_admin}, quoting"
        f" submission identifier {submission_id}, to request additional assistance.\n"
        f"\n"
        f"arXiv admin\n"
        f"\n"
        f"\n"
        f"{summary}\n"
    )

_REP_SUBMISSION_BODY = """\
Dear {name},

TODO: replacement confirmation email body for arXiv replacement {submission_id} of {arxiv_id}.

Regards,
arXiv Support


{summary}
"""

_WDR_SUBMISSION_BODY = """\
Dear {name},

TODO: withdrawal confirmation email body for arXiv withdrawal of {arxiv_id} (submission {submission_id}).

Regards,
arXiv Support


{summary}
"""

_CROSS_SUBMISSION_BODY = """\
Dear {name},

TODO: cross-list confirmation email body for arXiv cross to {new_categories} for {arxiv_id} (submission {submission_id}).

Regards,
arXiv Support


{summary}
"""

_JREF_SUBMISSION_BODY = """\
Dear {name},

TODO: journal-ref confirmation email body for arXiv journal ref for {arxiv_id} (submission {submission_id}).

Regards,
arXiv Support


{summary}
"""


def render_submission_summary(submission: Submission) -> str:
    """Render the plaintext "copy of the submission information" block.

    A ``write_to_string`` equivalent: an arXiv abs-style summary of the
    submission -- title / authors / categories, then the optional
    cross-reference fields, then the abstract. Empty fields are omitted. Text is
    included as entered (TeX is not converted to unicode). The ``\\\\`` lines
    are the conventional arXiv abs delimiters around the abstract.
    """
    md = submission.metadata

    categories = []
    if submission.primary_classification:
        categories.append(submission.primary_classification.category)
    categories.extend(submission.secondary_categories)

    lines = [
        f"Title: {md.title or ''}",
        f"Authors: {md.authors_display or ''}",
    ]
    if categories:
        lines.append(f"Categories: {' '.join(categories)}")
    for label, value in (
        ("Comments", md.comments),
        ("Report-no", md.report_num),
        ("MSC-class", md.msc_class),
        ("ACM-class", md.acm_class),
        ("Journal-ref", md.journal_ref),
        ("DOI", md.doi),
    ):
        if value:
            lines.append(f"{label}: {value}")

    abstract = (md.abstract or "").strip()
    return "{}\n\\\\\n{}\n\\\\".format("\n".join(lines), abstract)


def _is_auto_hold(submission: Submission) -> bool:
    """Return True when the email type should be overridden to ``auto_hold``.

    Currently only ``is_oversize`` is wired; the other four legacy conditions
    (``multiple``, ``linenos``, ``text_extraction_failure``, ``missing_pdf``)
    don't exist as Submission fields yet and will be added when those
    content-check pipelines are implemented.
    """
    return submission.is_oversize


def _build_subject_and_body(
    submission: Submission,
    to_name: str,
    config: SubmitConfig,
) -> tuple[str, str]:
    """Return ``(subject, body)`` for the finalize confirmation email.

    Checks for the auto_hold override first (``is_oversize``), then dispatches
    on :attr:`.Submission.submission_type`. Non-``new`` types send a placeholder
    body until full templates are implemented.
    """
    sid = submission.submission_id
    arxiv_id = submission.arxiv_id or ""
    summary = render_submission_summary(submission)

    if _is_auto_hold(submission):
        this_site = urlparse(config.url_for_user_dashboard).hostname or "arxiv.org"
        submit_url = f"https://{this_site}/submit/{sid}"
        subject = f"arXiv submission {sid}: On Hold"
        body = _render_auto_hold_body(
            submission=submission,
            submission_id=sid,
            submit_url=submit_url,
            this_site=this_site,
            www_admin=config.email_reply_to,
            summary=summary,
        )
        return subject, body

    sub_type = submission.submission_type or SubmissionType.NEW

    if sub_type == SubmissionType.NEW:
        subject = f"arXiv submission {sid}"
        body = _NEW_SUBMISSION_BODY.format(
            name=to_name,
            submission_id=sid,
            dashboard_url=config.url_for_user_dashboard,
            summary=summary,
        )
    elif sub_type == SubmissionType.REPLACEMENT:
        subject = f"arXiv replacement {sid} for {arxiv_id}"
        body = _REP_SUBMISSION_BODY.format(
            name=to_name,
            submission_id=sid,
            arxiv_id=arxiv_id,
            summary=summary,
        )
    elif sub_type == SubmissionType.WITHDRAWAL:
        subject = f"arXiv withdrawal of {arxiv_id}"
        body = _WDR_SUBMISSION_BODY.format(
            name=to_name,
            submission_id=sid,
            arxiv_id=arxiv_id,
            summary=summary,
        )
    elif sub_type == SubmissionType.CROSS_LIST:
        # Only the categories this cross is *adding*. The paper's existing
        # categories are inherited by the seed and are not what the subject
        # line means by "cross to".
        new_categories = " ".join(submission.new_cross_categories)
        subject = f"arXiv cross to {new_categories} for {arxiv_id}"
        body = _CROSS_SUBMISSION_BODY.format(
            name=to_name,
            submission_id=sid,
            arxiv_id=arxiv_id,
            new_categories=new_categories,
            summary=summary,
        )
    elif sub_type == SubmissionType.JOURNAL_REFERENCE:
        subject = f"arXiv journal ref for {arxiv_id}"
        body = _JREF_SUBMISSION_BODY.format(
            name=to_name,
            submission_id=sid,
            arxiv_id=arxiv_id,
            summary=summary,
        )
    else:
        subject = f"arXiv submission {sid}"
        body = _NEW_SUBMISSION_BODY.format(
            name=to_name,
            submission_id=sid,
            dashboard_url=config.url_for_user_dashboard,
            summary=summary,
        )

    return subject, body


def submitter_recipient(user: User) -> tuple[str, str]:
    """Resolve the ``(name, email)`` the confirmation email is sent to.

    ``user`` is the agent the email is addressed to -- in practice the
    ``creator`` of the :class:`.EmailSubmitterFinalizeMsg` event, which is the
    user that performed the ``FinalizeSubmission``. So the person doing the
    Finalize is the one who gets the email.

    If the normal submitter performs Finalize they will get the email.

    If an admin performs Finalize they will get the email.

    If CCSD performs Finalize CCSD will get the email eventhough they put a
    proxy on the submission.
    """
    match user:
        case System():
            return "", ""
        case _:
            return user.name, user.email


class EmailSubmitterFinalizeMsg(EventWithSideEffect):
    """Send the submitter the on-submit confirmation email.

    Emitted as a consequence of :class:`.FinalizeSubmission`. Sending is
    non-fatal: any failure is recorded on :attr:`error` and never raised, so it
    cannot abort the submit transaction (matching legacy, which wraps the email
    send in an ``eval``).
    """

    NAME = "email submitter on finalize"
    NAMED = "submitter finalize email sent"

    email_to: User
    """User who should get the email. Should be the creator of the `FinalizeSubmission` event."""

    error: Optional[str] = None
    """Set if the email could not be sent; the submit still succeeds."""

    msg_id: Optional[str] = None
    """Message id"""

    def validate_pre_lock(self, submission: Submission) -> None:
        """No precondition; this is a consequence of a validated finalize."""
        pass

    def execute(self, api: 'SubmitApi', submission: Submission) -> None:
        """Compose and send the confirmation email. Never raises."""
        try:
            if isinstance(self.email_to, System):
                # System actor: there is no one to email. Intentionally skip;
                logger.info("Submission %s: System actor, no confirmation "
                            "email sent", submission.submission_id)
                return

            to_name, to_email = submitter_recipient(self.email_to)
            if not to_email:
                # A real user with no email address; record it (not fatal).
                name = getattr(self.email_to, "name", "")
                self.error = (f"No email for user of type {type(self.email_to)} "
                              f"name '{name}'")
                logger.warning("Submission %s: %s", submission.submission_id,
                               self.error)
                return

            service = api.get_email_service()
            if service is None or not service.is_available():
                self.error = "email not configured or unavailable, no confirmation sent"
                logger.warning("Submission %s: %s", submission.submission_id,
                               self.error)
                return

            config = api.get_config()
            subject, body = _build_subject_and_body(
                submission=submission,
                to_name=to_name,
                config=config,
            )
            reply_to = (
                config.email_auto_hold_reply_to
                if _is_auto_hold(submission)
                else config.email_reply_to
            )
            msg_id, problems = service.send_email(
                to=[to_email],
                subject=subject,
                body=body,
                reply_to=reply_to,
            )
            self.msg_id = msg_id
            self.error = problems or None
        except Exception as e:  # noqa: BLE001 - email send must never abort submit
            self.error = f"failed to send confirmation email: {e}"
            logger.warning("Submission %s: %s", submission.submission_id,
                           self.error)

    def project(self, submission: Submission) -> Submission:
        """No state change; this event only sends mail."""
        return submission
