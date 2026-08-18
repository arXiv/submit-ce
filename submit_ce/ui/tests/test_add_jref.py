"""Tests for the create-a-journal-reference endpoint, ``POST /<paper_id>/add_jref``.

The endpoint is keyed on the *announced paper* rather than on a submission, and
lives in the ``paper`` blueprint (``routes/paper_id_ui.py``). It creates the jref
submission and hands off to that jref's own edit page, ``ui.jref``.
"""
from http import HTTPStatus as status

from arxiv.db import Session
from arxiv.db import models as classic
from flask import current_app

from submit_ce.domain.agent import InternalClient
from submit_ce.domain.event import CreateSubmissionVersion
from submit_ce.implementations.legacy_implementation.models import \
    Submission as LegacyRow

from .csrf_util import parse_csrf_token


def _csrf_token(client):
    """A token from the dashboard, where the Add Journal Reference button is."""
    response = client.get('/')
    assert response.status_code == status.OK
    return parse_csrf_token(response)


def _jref_rows(paper_id):
    with Session() as session:
        return session.query(classic.Submission) \
                      .filter(classic.Submission.doc_paper_id == paper_id) \
                      .filter(classic.Submission.type == 'jref').all()


def test_dashboard_offers_the_button_for_an_announced_paper(
        app, authorized_client, published_submission):
    """The entry point is a POST form on the dashboard, keyed on the paper id.

    Guards the `url_for('paper.add_jref')` in the template: a stale endpoint
    name there is a 500 on the dashboard, not a merely broken link.

    The paper reaches the page through `load_documents_for_user`;
    `load_submissions_for_user` filters to classic status 0/1/2/4 and never
    returns an announced row.
    """
    _, paper_id = published_submission

    response = authorized_client.get('/')

    assert response.status_code == status.OK
    assert f'action="/{paper_id}/add_jref"'.encode() in response.data
    assert b'Add Journal Reference' in response.data


def test_post_creates_a_jref_and_redirects_to_its_edit_page(
        app, authorized_client, published_submission):
    """The happy path: a new jref row, and the user lands on its edit page."""
    submission, paper_id = published_submission

    response = authorized_client.post(
        f'/{paper_id}/add_jref',
        data={'csrf_token': _csrf_token(authorized_client)})

    assert response.status_code == status.SEE_OTHER

    with app.app_context():
        rows = _jref_rows(paper_id)
        assert len(rows) == 1
        row = rows[0]
        # Created but not submitted; the values are entered on the edit page.
        assert row.status == LegacyRow.WORKING
        assert row.submission_id != int(submission.submission_id)
        assert response.headers['Location'].endswith(
            f'/{row.submission_id}/jref')
        # Seeded from the announced paper.
        assert row.title == submission.metadata.title
        assert row.version == submission.version

    # And that edit page is reachable, prefilled from the paper.
    response = authorized_client.get(response.headers['Location'])
    assert response.status_code == status.OK
    assert b'Journal reference' in response.data


def test_second_post_resumes_the_jref_in_progress(app, authorized_client,
                                                  published_submission):
    """A paper gets one journal reference at a time.

    Pressing the button again (or refreshing) must not fail and must not create
    a second row -- the user is sent back to the jref already in progress.
    """
    _, paper_id = published_submission
    endpoint = f'/{paper_id}/add_jref'

    first = authorized_client.post(
        endpoint, data={'csrf_token': _csrf_token(authorized_client)})
    assert first.status_code == status.SEE_OTHER

    second = authorized_client.post(
        endpoint, data={'csrf_token': _csrf_token(authorized_client)})

    assert second.status_code == status.SEE_OTHER
    assert second.headers['Location'] == first.headers['Location']
    with app.app_context():
        assert len(_jref_rows(paper_id)) == 1


def test_blocked_when_another_submission_is_in_progress(
        app, authorized_user, authorized_client, published_submission):
    """A paper with an in-progress replacement cannot take a journal reference.

    `CreateJrefSubmission.validate_under_lock` rejects it; the user gets the
    explanatory page rather than a 500.
    """
    submission, paper_id = published_submission
    with app.app_context():
        current_app.api.save(
            CreateSubmissionVersion(creator=authorized_user,
                                    client=InternalClient(name='test_add_jref')),
            submission_id=submission.submission_id)

    response = authorized_client.post(
        f'/{paper_id}/add_jref',
        data={'csrf_token': _csrf_token(authorized_client)})

    assert response.status_code == status.OK
    assert b'already has a submission in progress' in response.data
    with app.app_context():
        assert _jref_rows(paper_id) == []


def test_unknown_paper_is_not_found(app, authorized_client,
                                    published_submission):
    """There is no paper to annotate."""
    response = authorized_client.post(
        '/9999.99999/add_jref',
        data={'csrf_token': _csrf_token(authorized_client)})

    assert response.status_code == status.NOT_FOUND


def test_get_is_not_allowed(app, authorized_client, published_submission):
    """Creating a submission is a write; the route is POST only."""
    _, paper_id = published_submission

    response = authorized_client.get(f'/{paper_id}/add_jref')

    assert response.status_code == status.METHOD_NOT_ALLOWED
    with app.app_context():
        assert _jref_rows(paper_id) == []


def test_post_without_csrf_token_is_rejected(app, authorized_client,
                                             published_submission):
    """The button posts a token; a request without one creates nothing."""
    _, paper_id = published_submission

    response = authorized_client.post(f'/{paper_id}/add_jref', data={})

    assert response.status_code == status.BAD_REQUEST
    with app.app_context():
        assert _jref_rows(paper_id) == []
