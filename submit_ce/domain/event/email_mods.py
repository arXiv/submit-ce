"""Event that emails category moderators when a proposal is made.

Emitted as a consequence of :class:`.ProposeClassification` for moderator-made
proposals (system/classifier proposals are silent, matching legacy). It resolves
which moderators to notify via :meth:`.SubmitApi.moderators_for_categories` and
sends the notification.

Sending is non-fatal: any failure is recorded on :attr:`error` and never raised,
so it cannot abort the transaction.

Recipient/header composition mirrors the legacy proposal email
(``arXiv::Submit::Email::OnAdminLog``):

- ``To``: the resolved moderator emails, or ``local-admin`` if there are none.
- ``Reply-To``: ``mod-admin`` followed by the moderator emails.
- ``Bcc``: ``local-admin`` (omitted when falling back to a ``local-admin`` ``To``).
- The submitter is never a recipient; their name appears only in the subject.

"""

from typing import List, Optional, TYPE_CHECKING

from pydantic import Field

from ..submission import Submission
from .base import EventWithSideEffect

if TYPE_CHECKING:
    from submit_ce.api.submit import SubmitApi

import logging
logger = logging.getLogger(__name__)


class EmailProposalModeratorsMsg(EventWithSideEffect):
    """Notify the moderators of the affected categories that a proposal was made."""

    NAME = "email moderators on proposal"
    NAMED = "proposal moderators emailed"

    proposed_category: Optional[str] = None
    is_primary: bool = False
    comment: Optional[str] = None
    proposer_name: Optional[str] = None
    """Display name of the moderator who made the proposal."""

    error: Optional[str] = None
    """Set if the email could not be sent; the proposal still succeeds."""

    msg_id: Optional[str] = None

    def validate_pre_lock(self, submission: Submission) -> None:
        """No precondition; this is a consequence of a validated proposal."""
        pass

    def execute(self, api: 'SubmitApi', submission: Submission) -> None:
        """Resolve moderators, compose, and send. Never raises."""
        try:
            service = api.get_email_service()
            if service is None or not service.is_available():
                self.error = ("email not configured or unavailable, no moderator"
                              " notification sent")
                logger.warning("Submission %s: %s", submission.submission_id,
                               self.error)
                return

            categories_to_email=self.categories_to_email(submission)
            emails = [mod.email for mod in
                      api.moderators_for_categories(categories_to_email)]

            config = api.get_config()
            subject, body = self._build_subject_and_body(submission)

            if emails:
                to = emails
                reply_to = ",".join([config.mod_reply_to_email] + emails)
                bcc: Optional[List[str]] = [config.archival_email]
            else:
                # No moderators for these categories: fall back to local-admin.
                to = [config.archival_email]
                reply_to = config.mod_reply_to_email
                bcc = None
                logger.info("Submission %s: no moderators for %s; proposal "
                            "notification sent to %s", submission.submission_id,
                            categories_to_email, config.archival_email)

            msg_id, problems = service.send_email(
                to=to,
                subject=subject,
                body=body,
                reply_to=reply_to,
                bcc=bcc,
            )
            self.msg_id = msg_id
            self.error = problems or None
        except Exception as e:  # noqa: BLE001 - email send must never abort the save
            self.error = f"failed to send moderator proposal email: {e}"
            logger.warning("Submission %s: %s", submission.submission_id,
                           self.error)

    def categories_to_email(self, submission: Submission) -> list[str]:
        """
        For a primary proposal the affected categories also include the
        submission's current primary and any other unresolved primary proposals,
        so their moderators are notified too.

        For secondary, just the mods of the proposed secondary are emailed
        """
        cats = {self.proposed_category}
        if self.is_primary:
            if submission.primary_classification:
                cats.add(submission.primary_classification.category)
            for proposal in submission.proposals.values():
                if proposal.is_primary and proposal.is_unresolved:
                    cats.add(proposal.category)

        return sorted(set(c for c in cats if c))

    def _build_subject_and_body(self, submission: Submission) -> tuple[str, str]:
        """Compose the proposal notification ``(subject, body)``."""
        sid = submission.submission_id
        categories = []
        if submission.primary_classification:
            categories.append(submission.primary_classification.category)
        categories.extend(submission.secondary_categories)
        categories_str = " ".join(categories)

        submitter_name = getattr(submission.creator, "name", "") or ""
        prefix = "Action Required: " if submission.is_on_hold else "Re: "
        subject = (f"{prefix}arXiv submission {sid} to {categories_str} "
                   f"by {submitter_name}")

        type_str = "primary" if self.is_primary else "secondary"
        proposer = self.proposer_name or "a moderator"
        lines = [
            f"A category proposal has been made on arXiv submission {sid}.",
            "",
            f"Proposed: {self.proposed_category} as {type_str}",
        ]
        if self.comment:
            lines.append(f"Comment: {self.comment}")
        lines += [
            f"Proposed by: {proposer}",
            "",
            f"Current categories: {categories_str or '[no primary]'}",
            f"Submitted by: {submitter_name}",
        ]
        return subject, "\n".join(lines) + "\n"

    def project(self, submission: Submission) -> Submission:
        """No state change; this event only sends mail."""
        return submission
