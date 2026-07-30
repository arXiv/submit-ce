"""Tests for the 'Manage Submissions' dashboard.

The page has two lists from two api calls: active submissions
(`load_submissions_for_user`) and announced papers
(`load_documents_for_user`). The announced ones carry the per-paper actions,
including the Add Journal Reference button.
"""
from arxiv.db import Session
from arxiv.db import models as classic
from flask import current_app

from submit_ce.domain.agent import InternalClient
from submit_ce.domain.event import CreateSubmissionVersion
from submit_ce.domain.event.request import RequestWithdrawal


def _client():
    return InternalClient(name='test_manage_submissions')


def _document_id_for(paper_id):
    with Session() as session:
        return session.query(classic.Submission) \
                      .filter(classic.Submission.doc_paper_id == paper_id) \
                      .filter(classic.Submission.type == 'new').one().document_id


def test_user_page(authorized_client, published_submission, sub_created, submitted_submission):
    """User page with published, submitted and unsubmitted."""
    resp = authorized_client.get("/")
    assert resp and resp.status_code == 200
    assert b"working" in resp.data and b"submitted" in resp.data


def test_announced_paper_is_listed(app, authorized_client,
                                   published_submission):
    """An announced paper shows up with its identifier, title and actions."""
    submission, paper_id = published_submission

    resp = authorized_client.get('/')

    assert resp.status_code == 200
    body = resp.data.decode()
    assert 'No announced articles' not in body
    assert paper_id in body
    assert submission.metadata.title in body
    # All four per-paper actions, three keyed on the announced submission and
    # Add Journal Reference keyed on the paper.
    assert f'/{submission.submission_id}/replace' in body
    assert f'/{submission.submission_id}/withdraw' in body
    assert f'/{submission.submission_id}/request_cross' in body
    assert f'action="/{paper_id}/add_jref"' in body


def test_announced_paper_shows_its_primary_category(app, authorized_client,
                                                    published_submission):
    """The category comes from `arXiv_document_category` when the paper has it."""
    _, paper_id = published_submission
    with app.app_context():
        with Session() as session:
            session.add(classic.DocumentCategory(
                document_id=_document_id_for(paper_id),
                category='astro-ph.CO', is_primary=1))
            session.commit()

    resp = authorized_client.get('/')

    assert b'astro-ph.CO' in resp.data


def test_announced_paper_without_document_categories(app, authorized_client,
                                                     published_submission):
    """A paper announced here has no `arXiv_document_category` rows.

    Those are written by the legacy publish pipeline, so the page has to fall
    back to the announced submission's classification rather than blow up on a
    `None`.
    """
    _, paper_id = published_submission

    resp = authorized_client.get('/')

    assert resp.status_code == 200
    assert b'astro-ph.GA' in resp.data


def test_paper_with_submission_in_progress_offers_no_actions(
        app, authorized_user, authorized_client, published_submission):
    """A paper takes one submission at a time.

    While a replacement is in progress the buttons would only lead to the
    blocked page, so the page says what is in progress instead.
    """
    submission, paper_id = published_submission
    with app.app_context():
        current_app.api.save(
            CreateSubmissionVersion(creator=authorized_user, client=_client()),
            submission_id=submission.submission_id)

    resp = authorized_client.get('/')

    body = resp.data.decode()
    assert 'Replacement in progress' in body
    # Asserted per paper, not on the whole page: the test database is shared, so
    # this user has announced papers from other tests, which do offer the button.
    assert f'action="/{paper_id}/add_jref"' not in body


def test_paper_with_a_withdrawal_request_offers_no_actions(
        app, authorized_user, authorized_client, published_submission):
    """A withdrawal request is an active wdr submission on the paper.

    Not `Submission.active_user_requests`, which the page cannot see:
    `to_submission` builds a submission from its classic row and never rebuilds
    `user_requests`.
    """
    submission, paper_id = published_submission
    with app.app_context():
        current_app.api.save(
            RequestWithdrawal(creator=authorized_user, client=_client(),
                              reason='the data were wrong'),
            submission_id=submission.submission_id)

    resp = authorized_client.get('/')

    body = resp.data.decode()
    assert 'Withdrawal in progress' in body
    assert f'action="/{paper_id}/add_jref"' not in body
