"""Tests for the submission application as a whole."""
import pytest
from http import HTTPStatus as status

from arxiv.db import Session
import arxiv.db.models as classic



from submit_ce.ui.tests.csrf_util import parse_csrf_token


@pytest.mark.skip(reason="source_format not yet persisted")
def test_withdrawl_workflow(app, authorized_client, published_submission):
    """Tests that progress through the withdrawal request workflow."""
    client = authorized_client
    submission, paper_id = published_submission
    submission_id = submission.submission_id
    def _parse_csrf_token(response):
        return parse_csrf_token(response)


    """User requests withdrawal of a announced submission."""
    endpoint = f'/{submission_id}/withdraw'
    response = client.get(endpoint)
    assert response.status_code == status.OK
    assert response.content_type == 'text/html; charset=utf-8'
    assert b'Request withdrawal' in response.data
    token = _parse_csrf_token(response)

    # Set the withdrawal reason, but make it huge.
    request_data = {'withdrawal_reason': 'This is the reason' * 400,
                    'csrf_token': token}
    response = client.post(endpoint, data=request_data,
                                )
    assert response.status_code == status.OK
    token = _parse_csrf_token(response)

    # Set the withdrawal reason to something reasonable (ha).
    request_data = {'withdrawal_reason': 'This is the reason',
                    'csrf_token': token}
    response = client.post(endpoint, data=request_data,
                                )
    assert response.status_code == status.OK
    assert response.content_type == 'text/html; charset=utf-8'
    assert b'Confirm and Submit' in response.data
    token = _parse_csrf_token(response)

    # Confirm the withdrawal request.
    request_data['confirmed'] = True
    request_data['csrf_token'] = token
    response = client.post(endpoint, data=request_data,
                                )
    assert response.status_code == status.SEE_OTHER

    with app.app_context():
        with Session() as session:
            # What happened.
            db_submissions = session.query(classic.Submission) \
                .filter(classic.Submission.doc_paper_id == paper_id)
            assert db_submissions.count() == 2, "Creates a second row for the withdrawal"
            db_submission = db_submissions \
                .order_by(classic.Submission.submission_id.desc()) \
                .first()
            assert db_submission.type == 'wdr'
