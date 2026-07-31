"""Tests for `FinalizeJrefSubmission` against the classic database.

These exercise the real `api.save` path: the jref's own row moving from
WORKING to SUBMITTED with a `submit_time`, and the submitter confirmation email
sent as a consequence.
"""
import pytest
from arxiv.db import Session
from arxiv.db import models as classic
from flask import current_app

from submit_ce.domain.agent import InternalClient
from submit_ce.domain.event import CreateJrefSubmission, \
    EmailSubmitterFinalizeMsg, FinalizeJrefSubmission, SetJournalReference
from submit_ce.domain.exceptions import InvalidEvent
from submit_ce.domain.submission import Submission
from submit_ce.implementations.email.email_in_memory import EmailInMemory
from submit_ce.implementations.legacy_implementation.models import \
    Submission as LegacyRow

from .test_create_jref_submission import announced_paper  # noqa: F401

JOURNAL_REF = 'Phys. Rev. D 100, 1 (2019)'


def _row(submission_id):
    with Session() as session:
        return session.query(classic.Submission) \
                      .filter(classic.Submission.submission_id
                              == int(submission_id)).one()


@pytest.fixture
def working_jref(app, authorized_user, announced_paper):  # noqa: F811
    """An in-progress jref carrying a journal reference, ready to submit."""
    announced, paper_id, _ = announced_paper
    ua = InternalClient(name='test_finalize_jref')
    with app.app_context():
        jref, _ = current_app.api.save(CreateJrefSubmission(
            creator=authorized_user, client=ua, paper_id=paper_id))
        current_app.api.save(
            SetJournalReference(creator=authorized_user, client=ua,
                                journal_ref=JOURNAL_REF),
            submission_id=jref.submission_id)
    return jref, announced, paper_id, ua


def test_finalize_submits_the_jref_row(app, authorized_user, working_jref):
    """The jref's own row goes to SUBMITTED with a submit_time."""
    jref, announced, _, ua = working_jref

    with app.app_context():
        assert _row(jref.submission_id).status == LegacyRow.WORKING

        after, _ = current_app.api.save(
            FinalizeJrefSubmission(creator=authorized_user, client=ua),
            submission_id=jref.submission_id)

        assert after.status == Submission.SUBMITTED
        assert after.submitted is not None

        row = _row(jref.submission_id)
        assert row.type == 'jref'
        assert row.status == LegacyRow.SUBMITTED
        assert row.submit_time is not None
        assert row.journal_ref == JOURNAL_REF

        # The announced row is untouched: a jref is its own submission.
        assert _row(announced.submission_id).status == LegacyRow.ANNOUNCED


def test_finalized_jref_replays_as_submitted(app, authorized_user,
                                             working_jref):
    """The status and submit time survive a reload from the event history."""
    jref, _, _, ua = working_jref

    with app.app_context():
        after, _ = current_app.api.save(
            FinalizeJrefSubmission(creator=authorized_user, client=ua),
            submission_id=jref.submission_id)

        loaded, history = current_app.api.get_with_history(jref.submission_id)

        assert loaded.status == Submission.SUBMITTED
        # The submit time comes from the event's `created`, so it survives the
        # replay -- but stored timestamps come back naive, so compare the
        # wall clock rather than the tzinfo.
        assert loaded.submitted is not None
        assert loaded.submitted.replace(tzinfo=None) \
            == after.submitted.replace(tzinfo=None)
        assert len([e for e in history
                    if isinstance(e, FinalizeJrefSubmission)]) == 1


def test_finalize_emails_the_submitter(app, authorized_user, working_jref):
    """Exactly one email, to the submitter, with the jref subject."""
    jref, _, paper_id, ua = working_jref

    with app.app_context():
        service = EmailInMemory()
        original = current_app.api.email_service
        current_app.api.email_service = service
        try:
            after, _ = current_app.api.save(
                FinalizeJrefSubmission(creator=authorized_user, client=ua),
                submission_id=jref.submission_id)
        finally:
            current_app.api.email_service = original

        # No moderator notification: a jref never reaches moderation.
        assert len(service.sent) == 1
        sent = service.sent[0]
        assert sent.to == [after.contact_email]
        assert sent.subject == f"arXiv journal ref for {paper_id}"
        assert sent.reply_to == "EMAIL_REPLY_TO@example.org"

        # The consequence is persisted as a real event in the history.
        _, history = current_app.api.get_with_history(jref.submission_id)
        emails = [e for e in history
                  if isinstance(e, EmailSubmitterFinalizeMsg)]
        assert len(emails) == 1
        assert emails[0].error is None


def test_email_failure_does_not_block_the_submit(app, authorized_user,
                                                 working_jref):
    """A mail problem must not leave the jref unsubmitted."""
    class _RaisingService(EmailInMemory):
        def send_email(self, *args, **kwargs):
            raise RuntimeError("smtp boom")

    jref, _, _, ua = working_jref

    with app.app_context():
        original = current_app.api.email_service
        current_app.api.email_service = _RaisingService()
        try:
            after, _ = current_app.api.save(
                FinalizeJrefSubmission(creator=authorized_user, client=ua),
                submission_id=jref.submission_id)
        finally:
            current_app.api.email_service = original

        assert after.status == Submission.SUBMITTED
        assert _row(jref.submission_id).status == LegacyRow.SUBMITTED

        _, history = current_app.api.get_with_history(jref.submission_id)
        emails = [e for e in history
                  if isinstance(e, EmailSubmitterFinalizeMsg)]
        assert len(emails) == 1
        assert emails[0].error is not None


def test_rejects_an_announced_submission(app, authorized_user, working_jref):
    """Aimed at the announced paper instead of the jref, this does nothing.

    The announced row is not a jref, and it must not be flipped to SUBMITTED.
    """
    _, announced, _, ua = working_jref

    with app.app_context():
        with pytest.raises(InvalidEvent, match='Not a journal reference'):
            current_app.api.save(
                FinalizeJrefSubmission(creator=authorized_user, client=ua),
                submission_id=announced.submission_id)

        assert _row(announced.submission_id).status == LegacyRow.ANNOUNCED


def test_rejects_a_second_finalize(app, authorized_user, working_jref):
    """Submitting an already-submitted jref is rejected, and changes nothing."""
    jref, _, _, ua = working_jref

    with app.app_context():
        current_app.api.save(
            FinalizeJrefSubmission(creator=authorized_user, client=ua),
            submission_id=jref.submission_id)
        submit_time = _row(jref.submission_id).submit_time

        with pytest.raises(InvalidEvent, match='already finalized'):
            current_app.api.save(
                FinalizeJrefSubmission(creator=authorized_user, client=ua),
                submission_id=jref.submission_id)

        row = _row(jref.submission_id)
        assert row.status == LegacyRow.SUBMITTED
        assert row.submit_time == submit_time
