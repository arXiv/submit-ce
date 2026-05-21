"""Tests for the withdraw submission UI controller."""
from http import HTTPStatus as status

from flask import current_app
import pytest

import arxiv.db.models as classic
from arxiv.db import Session

from submit_ce.ui.tests.csrf_util import parse_csrf_token


def test_wdr_no_submission(app, authorized_client):
    """GET on a submission_id that doesn't exist returns NOT_FOUND."""
    response = authorized_client.get('/1234/withdraw')
    assert response.status_code == status.NOT_FOUND


def test_wdr_submission_not_published(app, authorized_client, submitted_submission):
    """Withdraw on a finalized-but-not-announced submission is rejected.

    The controller flashes failure and 303-redirects to create_submission.
    """
    sid = submitted_submission.submission_id
    response = authorized_client.get(f'/{sid}/withdraw')
    assert response.status_code == status.SEE_OTHER
    assert '/' in response.headers.get('Location', '')


def test_wdr_submission_not_owned_by_user(app, authorized_client, published_submission):
    """A submission owned by a different user is not editable by us.

    Achieved by flipping the DB row's submitter_id to a non-matching value;
    the route's `is_owner` authorizer then returns False and `scoped` answers
    with a non-success status (typically FORBIDDEN).
    """
    submission, _paper_id = published_submission
    sid = submission.submission_id

    with app.app_context():
        with Session() as session:
            row = session.query(classic.Submission).get(sid)
            row.submitter_id = 99999  # not the test user (user_id=10)
            session.add(row)
            session.commit()

        response = authorized_client.get(f'/{sid}/withdraw')

    assert response.status_code in (
        status.FORBIDDEN, status.FOUND, status.SEE_OTHER, status.UNAUTHORIZED,
    ), f"expected an unauthorized/forbidden/redirect, got {response.status_code}"


def test_wdr_published_submission_succeeds(app, authorized_client, published_submission):
    """GET on a published submission renders the withdrawal form, POST creates a wdr row."""
    submission, paper_id = published_submission
    sid = submission.submission_id

    get1 = authorized_client.get(f'/{sid}/withdraw')
    assert get1.status_code == status.OK
    assert b'withdrawal' in get1.data.lower() or b'Withdraw' in get1.data

    post1 = authorized_client.post(
        f'/{sid}/withdraw',
        data={
            'csrf_token': parse_csrf_token(get1),
            'withdrawal_reason': f'Test WDR from {__file__}, found a serious error in section 3.',
            'confirmed': 'y',
        },
    )
    assert post1.status_code == status.SEE_OTHER

    with app.app_context():
        with Session() as session:
            original = session.query(classic.Submission).get(sid)
            assert original is not None, "original submission row should still exist"
            wdr_rows = session.query(classic.Submission).filter(
                classic.Submission.doc_paper_id == paper_id,
                classic.Submission.type == 'wdr',
            ).all()
            assert len(wdr_rows) == 1, \
                f"expected exactly one 'wdr' row for {paper_id}, got {len(wdr_rows)}"
            wdr = wdr_rows[0]
            assert wdr.submission_id != sid, \
                "withdrawal row should be a new row, not the original submission"
            assert wdr.is_withdrawn == 1
            assert wdr.must_process == 0
            assert wdr.is_single_file == 1
            assert wdr.source_format == 'withdrawn'

            workspace = app.api.get_file_store().get_workspace(wdr.submission_id)
            assert workspace
            assert workspace.file_count == 1
            file = workspace.files[0]
            assert file.name == "withdrawn"
            with app.api.get_file_store().get_source_file(wdr.submission_id, file.path) as fh:
                assert fh.read() == '%auto-ignore'
