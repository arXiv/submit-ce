"""Tests for the cross-list endpoints.

``POST /<paper_id>/add_cross`` is keyed on the *announced paper* and lives in the
``paper`` blueprint (``routes/paper_id_ui.py``); it creates the cross submission
and hands off to that cross's own edit page, ``ui.cross``, where categories are
added and removed and the cross is finally submitted.
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


def _csrf_token(client, path='/'):
    """A token from the page the relevant button lives on."""
    response = client.get(path)
    assert response.status_code == status.OK
    return parse_csrf_token(response)


def _cross_rows(paper_id):
    with Session() as session:
        return session.query(classic.Submission) \
                      .filter(classic.Submission.doc_paper_id == paper_id) \
                      .filter(classic.Submission.type == 'cross').all()


def _categories(submission_id):
    with Session() as session:
        rows = session.query(classic.SubmissionCategory) \
                      .filter(classic.SubmissionCategory.submission_id
                              == int(submission_id)).all()
        return {(c.category, bool(c.is_published)) for c in rows}


def _start_cross(client, paper_id):
    """Create a cross and return the URL of its edit page."""
    response = client.post(f'/{paper_id}/add_cross',
                           data={'csrf_token': _csrf_token(client)})
    assert response.status_code == status.SEE_OTHER
    return response.headers['Location']


def test_dashboard_offers_the_button_for_an_announced_paper(
        app, authorized_client, published_submission):
    """The entry point is a POST form on the dashboard, keyed on the paper id.

    Guards the `url_for('paper.add_cross')` in the template: a stale endpoint
    name there is a 500 on the dashboard, not a merely broken link.
    """
    _, paper_id = published_submission

    response = authorized_client.get('/')

    assert response.status_code == status.OK
    assert f'action="/{paper_id}/add_cross"'.encode() in response.data
    assert b'Add cross-list' in response.data


def test_post_creates_a_cross_and_redirects_to_its_edit_page(
        app, authorized_client, published_submission):
    """The happy path: a new cross row, and the user lands on its edit page."""
    submission, paper_id = published_submission

    location = _start_cross(authorized_client, paper_id)

    with app.app_context():
        rows = _cross_rows(paper_id)
        assert len(rows) == 1
        row = rows[0]
        # Created but not submitted; categories are chosen on the edit page.
        assert row.status == LegacyRow.WORKING
        assert row.submission_id != int(submission.submission_id)
        assert location.endswith(f'/{row.submission_id}/cross')
        # Seeded from the announced paper.
        assert row.title == submission.metadata.title
        assert row.version == submission.version

    response = authorized_client.get(location)
    assert response.status_code == status.OK
    assert b'Add Cross-List Categories' in response.data
    # Nothing added yet, so there is nothing to submit.
    assert b'No categories added yet' in response.data


def test_second_post_resumes_the_cross_in_progress(app, authorized_client,
                                                   published_submission):
    """A paper gets one cross-list at a time.

    Pressing the button again (or refreshing) must not fail and must not create
    a second row -- the user is sent back to the cross already in progress.
    """
    _, paper_id = published_submission

    first = _start_cross(authorized_client, paper_id)
    second = _start_cross(authorized_client, paper_id)

    assert second == first
    with app.app_context():
        assert len(_cross_rows(paper_id)) == 1


def test_add_then_remove_a_category(app, authorized_client,
                                   published_submission):
    """Categories are added and removed one POST at a time, as in legacy."""
    _, paper_id = published_submission
    location = _start_cross(authorized_client, paper_id)

    added = authorized_client.post(location, data={
        'csrf_token': _csrf_token(authorized_client, location),
        'operation': 'add', 'category': 'cs.DL'})

    assert added.status_code == status.OK
    assert b'cs.DL' in added.data
    with app.app_context():
        submission_id = _cross_rows(paper_id)[0].submission_id
        assert ('cs.DL', False) in _categories(submission_id)

    removed = authorized_client.post(location, data={
        'csrf_token': _csrf_token(authorized_client, location),
        'operation': 'remove', 'category': 'cs.DL'})

    assert removed.status_code == status.OK
    assert b'No categories added yet' in removed.data
    with app.app_context():
        assert 'cs.DL' not in {c for c, _ in _categories(submission_id)}


def test_submitting_the_cross(app, authorized_client, published_submission):
    """With a category added, the cross can be submitted."""
    _, paper_id = published_submission
    location = _start_cross(authorized_client, paper_id)
    authorized_client.post(location, data={
        'csrf_token': _csrf_token(authorized_client, location),
        'operation': 'add', 'category': 'cs.DL'})

    response = authorized_client.post(location, data={
        'csrf_token': _csrf_token(authorized_client, location),
        'confirmed': '1'})

    assert response.status_code == status.SEE_OTHER
    with app.app_context():
        assert _cross_rows(paper_id)[0].status == LegacyRow.SUBMITTED


def test_cannot_submit_a_cross_with_no_categories(app, authorized_client,
                                                  published_submission):
    """Legacy: "Please add categories before submitting"."""
    _, paper_id = published_submission
    location = _start_cross(authorized_client, paper_id)

    response = authorized_client.post(location, data={
        'csrf_token': _csrf_token(authorized_client, location),
        'confirmed': '1'})

    assert response.status_code == status.BAD_REQUEST
    with app.app_context():
        assert _cross_rows(paper_id)[0].status == LegacyRow.WORKING


def test_editing_a_submitted_cross_unsubmits_it(app, authorized_client,
                                                published_submission):
    """Legacy `user_updated`: an edit after submitting returns it to working."""
    _, paper_id = published_submission
    location = _start_cross(authorized_client, paper_id)
    authorized_client.post(location, data={
        'csrf_token': _csrf_token(authorized_client, location),
        'operation': 'add', 'category': 'cs.DL'})
    authorized_client.post(location, data={
        'csrf_token': _csrf_token(authorized_client, location),
        'confirmed': '1'})

    response = authorized_client.post(location, data={
        'csrf_token': _csrf_token(authorized_client, location),
        'operation': 'add', 'category': 'hep-th'})

    assert response.status_code == status.OK
    with app.app_context():
        row = _cross_rows(paper_id)[0]
        assert row.status == LegacyRow.WORKING
        assert ('hep-th', False) in _categories(row.submission_id)


def test_adding_a_disallowed_category_is_rejected(app, authorized_client,
                                                  published_submission):
    """`physics.gen-ph` never receives crosses, so the add is refused."""
    _, paper_id = published_submission
    location = _start_cross(authorized_client, paper_id)

    response = authorized_client.post(location, data={
        'csrf_token': _csrf_token(authorized_client, location),
        'operation': 'add', 'category': 'physics.gen-ph'})

    assert response.status_code == status.BAD_REQUEST
    with app.app_context():
        submission_id = _cross_rows(paper_id)[0].submission_id
        assert 'physics.gen-ph' not in {c for c, _ in _categories(submission_id)}


def test_blocked_when_the_paper_has_a_general_primary(
        app, authorized_client, published_submission):
    """A paper with a general primary category is not cross-listable.

    Rejected before any row is created, and the user gets the explanatory page
    with the reason rather than a 500.
    """
    submission, paper_id = published_submission
    with app.app_context():
        with Session() as session:
            document_id = session.query(classic.Submission) \
                .filter(classic.Submission.submission_id
                        == int(submission.submission_id)).one().document_id
            session.add(classic.DocumentCategory(
                document_id=document_id, category='physics.gen-ph',
                is_primary=1))
            session.commit()

    response = authorized_client.post(
        f'/{paper_id}/add_cross',
        data={'csrf_token': _csrf_token(authorized_client)})

    assert response.status_code == status.OK
    assert b'not appropriate for cross-listing' in response.data
    with app.app_context():
        assert _cross_rows(paper_id) == []


def test_blocked_when_another_submission_is_in_progress(
        app, authorized_user, authorized_client, published_submission):
    """A paper with an in-progress replacement cannot take a cross-list."""
    submission, paper_id = published_submission
    with app.app_context():
        current_app.api.save(
            CreateSubmissionVersion(creator=authorized_user,
                                    client=InternalClient(name='test_add_cross')),
            submission_id=submission.submission_id)

    response = authorized_client.post(
        f'/{paper_id}/add_cross',
        data={'csrf_token': _csrf_token(authorized_client)})

    assert response.status_code == status.OK
    assert b'already has a submission in progress' in response.data
    with app.app_context():
        assert _cross_rows(paper_id) == []


def test_unknown_paper_is_not_found(app, authorized_client,
                                   published_submission):
    """There is no paper to cross-list."""
    response = authorized_client.post(
        '/9999.99999/add_cross',
        data={'csrf_token': _csrf_token(authorized_client)})

    assert response.status_code == status.NOT_FOUND


def test_get_is_not_allowed(app, authorized_client, published_submission):
    """Creating a submission is a write; the route is POST only."""
    _, paper_id = published_submission

    response = authorized_client.get(f'/{paper_id}/add_cross')

    assert response.status_code == status.METHOD_NOT_ALLOWED
    with app.app_context():
        assert _cross_rows(paper_id) == []


def test_post_without_csrf_token_is_rejected(app, authorized_client,
                                             published_submission):
    """The button posts a token; a request without one creates nothing."""
    _, paper_id = published_submission

    response = authorized_client.post(f'/{paper_id}/add_cross', data={})

    assert response.status_code == status.BAD_REQUEST
    with app.app_context():
        assert _cross_rows(paper_id) == []
