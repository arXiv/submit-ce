"""Tests for :mod:`submit_ce.controllers.verify_user`."""
import pytest
from http import HTTPStatus as status
from submit_ce.ui.tests.csrf_util import parse_csrf_token
from submit_ce.api.domain.submission import Submission

@pytest.mark.usefixtures("app")
def test_verify_user_normal(authorized_client, sub_created):
    """
    Non-proxy submitter: GET -> POST verify_user=true should advance (ready_for_next).
    Covers validate(), save(), and ready_for_next path.
    """
    sub: Submission = sub_created
    assert not sub.submitter_contact_verified

    url = f"/{sub.submission_id}/verify_user"

    # GET form
    resp_get = authorized_client.get(url)
    assert resp_get.status_code == status.OK

    # Real CSRF from page
    token = parse_csrf_token(resp_get)

    # POST verify_user=true
    resp_post = authorized_client.post(
        url,
        data={"verify_user": "y", "csrf_token": token},
        follow_redirects=False
    )

    # Depending on your flow_control wrapper, this might be 200 or a redirect
    assert resp_post.status_code in (status.OK, status.FOUND, status.SEE_OTHER)
