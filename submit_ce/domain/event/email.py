"""Events that send email as a side effect.

Scope of this implementation: the "new submission" confirmation only.

TODO Per-type bodies (rep/wdr/cross/jref),

TODO the ``auto_hold`` override,

TODO ``Re:`` resubmit threading,

TODO proxy/admin recipient resolution,

TODO the full ``write_to_string`` abstract block
"""
from typing import Optional, TYPE_CHECKING

from ..submission import Submission
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
# TODO: parameterize the THIS_SITE too

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


Title: {title}
"""
# TODO: replace the bare "Title: ..." line with a full write_to_string-equivalent
# abstract block (title/authors/abstract/comments/categories).


class EmailSubmitterFinalizeMsg(EventWithSideEffect):
    """Send the submitter the on-submit confirmation email.

    Emitted as a consequence of :class:`.FinalizeSubmission`. Sending is
    non-fatal: any failure is recorded on :attr:`error` and never raised, so it
    cannot abort the submit transaction (matching legacy, which wraps the email
    send in an ``eval``).
    """

    NAME = "email submitter on finalize"
    NAMED = "submitter finalize email sent"

    error: Optional[str] = None
    """Set if the email could not be sent; the submit still succeeds."""

    def validate_pre_lock(self, submission: Submission) -> None:
        """No precondition; this is a consequence of a validated finalize."""
        pass

    def execute(self, api: 'SubmitApi', submission: Submission) -> None:
        """Compose and send the confirmation email. Never raises."""
        service = api.get_email_service()
        if service is None or not service.is_available():
            self.error = "email service unavailable; no confirmation sent"
            logger.warning("Submission %s: %s", submission.submission_id,
                           self.error)
            return

        config = api.get_config()
        subject = f"arXiv submission {submission.submission_id}"
        body = _NEW_SUBMISSION_BODY.format(
            name=submission.contact_name,
            submission_id=submission.submission_id,
            title=submission.metadata.title or "",
            dashboard_url=config.url_for_user_dashboard,
        )
        try:
            service.send_email(
                to=[submission.contact_email],
                subject=subject,
                body=body,
                reply_to=config.email_reply_to,
            )
        except Exception as e:  # noqa: BLE001 - email send must never abort submit
            self.error = f"failed to send confirmation email: {e}"
            logger.warning("Submission %s: %s", submission.submission_id,
                           self.error)

    def project(self, submission: Submission) -> Submission:
        """No state change; this event only sends mail."""
        return submission
