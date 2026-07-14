"""Event that emails category moderators when a submission is finalized.

Emitted as a consequence of :class:`.FinalizeSubmission` for the submission
types (``new``/``rep``/``wdr``/ ``cross``) and that are not auto-held. The type
gating itself lives in :meth:`.FinalizeSubmission.consequences`.

Recipient/header composition:

- Candidate moderators = union over the submission's categories and its
  unresolved proposed categories of category-level and archive-level moderators.
  Unlike the proposal email, ``no_web_email`` moderators are NOT excluded here,
  so the full candidate set is fetched and filtered per header in Python.
- ``To``: candidates without ``no_email``; falls back to ``archival_email`` when
  empty.
- ``Reply-To``: ``mod_reply_to_email`` followed by candidates without
  ``no_reply_to``.
- ``Bcc``: ``archival_email``, omitted when ``To`` fell back to it.

Sending is non-fatal: any failure is recorded on :attr:`error` and never raised,
so it cannot abort the finalize transaction.

"""

from typing import List, Optional, TYPE_CHECKING
from urllib.parse import urlparse

from ..submission import Submission, SubmissionType
from .base import EventWithSideEffect
from .email import render_submission_summary

if TYPE_CHECKING:
    from submit_ce.api.submit import SubmitApi

import logging
logger = logging.getLogger(__name__)


def _categories(submission: Submission) -> List[str]:
    """The submission's primary + secondary categories, in order."""
    cats: List[str] = []
    if submission.primary_classification:
        cats.append(submission.primary_classification.category)
    cats.extend(submission.secondary_categories)
    return cats


class EmailModeratorsFinalizeMsg(EventWithSideEffect):
    """Notify the moderators of the affected categories that a submission was finalized."""

    NAME = "email moderators on finalize"
    NAMED = "finalize moderators emailed"

    error: Optional[str] = None
    """Set if the email could not be sent; the finalize still succeeds."""

    msg_id: Optional[str] = None

    def validate_pre_lock(self, submission: Submission) -> None:
        """No precondition; this is a consequence of a validated finalize."""
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

            config = api.get_config()
            categories_to_email = self.categories_to_email(submission)
            # Fetch the full candidate set (no_web_email NOT excluded, per spec)
            # and compute the To / Reply-To sets ourselves from the opt-out flags.
            mods = api.moderators_for_categories(
                categories_to_email, exclude_no_web_email=False)

            to_mods = [m.email for m in mods if not m.no_email]
            reply_to_mods = [m.email for m in mods if not m.no_reply_to]

            if to_mods:
                to = to_mods
                bcc: Optional[List[str]] = [config.archival_email]
            else:
                # No eligible moderators: fall back to the archival admin and
                # drop the (now redundant) Bcc.
                to = [config.archival_email]
                bcc = None
                logger.info("Submission %s: no moderators for %s; finalize "
                            "notification sent to %s", submission.submission_id,
                            categories_to_email, config.archival_email)

            reply_to = ",".join([config.mod_reply_to_email] + reply_to_mods)

            subject, body = self._build_subject_and_body(submission, config)
            message_id, references = self._threading(submission, config)

            msg_id, problems = service.send_email(
                to=to,
                subject=subject,
                body=body,
                reply_to=reply_to,
                bcc=bcc,
                message_id=message_id,
                references=references,
            )
            self.msg_id = msg_id
            self.error = problems or None
        except Exception as e:  # noqa: BLE001 - email send must never abort finalize
            self.error = f"failed to send moderator finalize email: {e}"
            logger.warning("Submission %s: %s", submission.submission_id,
                           self.error)

    def categories_to_email(self, submission: Submission) -> List[str]:
        """Categories whose moderators should be notified.

        Union of the submission's categories and the categories of its
        unresolved proposals. Legacy uses the *new* (unpublished) categories;
        the model has no per-category published flag yet, so primary+secondary
        stands in as a safe superset.

        TODO: narrow to genuinely-new categories once published-category tracking exists.
        Currently legacy has no db or domain info about published categories.
        """
        cats = set(_categories(submission))
        for proposal in submission.proposals.values():
            if proposal.is_unresolved:
                cats.add(proposal.category)
        return sorted(c for c in cats if c)

    def _threading(self, submission: Submission, config) -> tuple[str, str]:
        """Stable ``(message_id, references)`` so resubmits thread together.

        Matches legacy ``<submit.<submission_id>@<site>>``.
        """
        site = urlparse(config.url_for_user_dashboard).hostname or "arxiv.org"
        message_id = f"<submit.{submission.submission_id}@{site}>"
        return message_id, message_id

    def _build_subject_and_body(self, submission: Submission, config) \
            -> tuple[str, str]:
        """Compose the per-type ``(subject, body)`` (spec §5).

        Dispatches on :attr:`.Submission.submission_type`. Variables the model
        does not yet expose (``submitter_warnings``, ``near_duplicates``, the
        real ``classifier_moderator_abstract``, genuinely "newly added"
        categories) are left as TODO placeholders, matching the precedent in
        ``email.py``. ``render_submission_summary`` stands in for the legacy
        ``classifier_moderator_abstract`` / ``write_to_string`` blocks.
        """
        sid = submission.submission_id
        arxiv_id = submission.arxiv_id or ""
        name = getattr(submission.creator, "name", "") or ""
        email = getattr(submission.creator, "email", "") or ""
        categories_str = " ".join(_categories(submission))
        review_url = f"{config.url_for_moderator_review}{sid}"
        summary = render_submission_summary(submission)

        # TODO: prefix "Re:" on a resubmit once that state is tracked.
        # TODO: render submitter_warnings / near_duplicates once those exist.

        sub_type = submission.submission_type or SubmissionType.NEW

        if sub_type == SubmissionType.REPLACEMENT:
            subject = f"arXiv replacement {sid} for {arxiv_id} by {name}"
            lines = []
            # TODO: only the genuinely added categories belong here.
            if categories_str:
                lines.append(f"Categories added: {categories_str}")
            lines += [f"View the replacement: {review_url}", "", summary]
            return subject, "\n".join(lines) + "\n"

        if sub_type == SubmissionType.WITHDRAWAL:
            subject = f"arXiv withdrawal {sid} for {arxiv_id} by {name}"
            body = f"View the withdrawal: {review_url}\n\n{summary}\n"
            return subject, body

        if sub_type == SubmissionType.CROSS_LIST:
            subject = (f"arXiv cross {sid} to {categories_str} for {arxiv_id} "
                       f"by {name}")
            body = (f"A crosslist has been added by submitter {name}, {email} "
                    f"for {arxiv_id}.\n\n"
                    f"View the submission: {review_url}\n\n{summary}\n")
            return subject, body

        # Default: SubmissionType.NEW
        subject = f"arXiv submission {sid} to {categories_str} by {name}"
        lines = []
        primary_proposals = [p.category for p in submission.proposals.values()
                             if p.is_primary and p.is_unresolved]
        if primary_proposals:
            lines.append("System-proposed primaries: "
                         + " ".join(sorted(primary_proposals)))
        lines += [f"View the submission: {review_url}", "", summary]
        return subject, "\n".join(lines) + "\n"

    def project(self, submission: Submission) -> Submission:
        """No state change; this event only sends mail."""
        return submission
