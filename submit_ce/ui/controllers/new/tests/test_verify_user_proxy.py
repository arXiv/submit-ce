"""Tests for :mod:`submit_ce.controllers.verify_user`."""
import pytest
from http import HTTPStatus as status
from submit_ce.ui.tests.csrf_util import parse_csrf_token
from submit_ce.domain.submission import Submission

@pytest.mark.usefixtures("app")
def test_verify_user_proxy_requires_fields(authorized_client, sub_created, monkeypatch):
    """
    Proxy submitter: first POST missing fields -> 400; second POST with fields -> advance.
    Covers may_proxy validation branch and both error/success paths.
    """
    sub: Submission = sub_created
    assert not sub.submitter_contact_verified
    url = f"/{sub.submission_id}/verify_user"

    # give the current authorized user the PROXY_SUBMISSION scope
    from arxiv.auth.auth import scopes
    from submit_ce.ui import auth as auth_mod
    # Patch only for the duration of this test: always return a user with PROXY_SUBMISSION
    user_client = auth_mod.user_and_client_from_session
    def fake_user_and_client(session):
        submitter, client = user_client(session)
        # ensure PROXY_SUBMISSION is present
        submitter.scopes = set(getattr(submitter, "scopes", [])) | {scopes.PROXY_SUBMISSION}
        return submitter, client

    monkeypatch.setattr(
        "submit_ce.ui.controllers.new.verify_user.user_and_client_from_session",
        fake_user_and_client
    )

    # GET form
    resp_get = authorized_client.get(url)
    assert resp_get.status_code == status.OK
    token = parse_csrf_token(resp_get)

    # 1) Test bad request: POST with verify_user=true but missing proxy fields -> BAD_REQUEST
    resp_bad = authorized_client.post(
        url,
        data={"verify_user": "y", "csrf_token": token},
        follow_redirects=False
    )
    assert resp_bad.status_code == status.BAD_REQUEST

    # 2) Test good request: POST with verify_user=true and valid proxy fields -> should advance
    resp_ok = authorized_client.post(
        url,
        data={
            "verify_user": "y",
            "proxy_name": "Jane Proxy",
            "proxy_email": "jane.proxy@example.org",
            "csrf_token": token,
        },
        follow_redirects=False
    )
    assert resp_ok.status_code in (status.OK, status.FOUND, status.SEE_OTHER)


@pytest.mark.usefixtures("app")
def test_verify_user_rejects_too_short_proxy_name(authorized_client, sub_created, monkeypatch):
    """A proxy name shorter than PublicUser allows used to be saved, after which
    every page that loads the submitter's submissions failed with a 500."""
    from arxiv.auth.auth import scopes
    from submit_ce.ui import auth as auth_mod
    real = auth_mod.user_and_client_from_session

    def as_proxy(session):
        submitter, client = real(session)
        submitter.scopes = set(getattr(submitter, "scopes", [])) | {scopes.PROXY_SUBMISSION}
        return submitter, client

    monkeypatch.setattr(
        "submit_ce.ui.controllers.new.verify_user.user_and_client_from_session", as_proxy)

    url = f"/{sub_created.submission_id}/verify_user"
    token = parse_csrf_token(authorized_client.get(url))
    resp = authorized_client.post(url, data={"verify_user": "y", "proxy_name": " A ",
                                             "proxy_email": "a@example.org", "csrf_token": token})
    assert resp.status_code == status.BAD_REQUEST
    assert authorized_client.get("/").status_code == status.OK


@pytest.fixture
def proxy_submitter(monkeypatch):
    """The logged-in user may proxy."""
    from arxiv.auth.auth import scopes
    from submit_ce.ui import auth as auth_mod
    real = auth_mod.user_and_client_from_session

    def as_proxy(session):
        submitter, client = real(session)
        submitter.scopes = set(getattr(submitter, "scopes", [])) | {scopes.PROXY_SUBMISSION}
        return submitter, client

    monkeypatch.setattr(
        "submit_ce.ui.controllers.new.verify_user.user_and_client_from_session", as_proxy)


def test_verify_user_proxy_submitting_as_self_needs_no_proxy_fields(
        authorized_client, sub_created, proxy_submitter):
    url = f"/{sub_created.submission_id}/verify_user"
    token = parse_csrf_token(authorized_client.get(url))
    resp = authorized_client.post(url, data={"verify_user": "y", "submit_as_self": "y",
                                             "action": "next", "csrf_token": token})
    assert resp.status_code == status.SEE_OTHER


def test_verify_user_proxy_submitting_as_self_records_no_proxy(
        app, authorized_client, sub_created, proxy_submitter):
    """With the box ticked, the proxy fields are ignored even when filled in."""
    url = f"/{sub_created.submission_id}/verify_user"
    token = parse_csrf_token(authorized_client.get(url))
    resp = authorized_client.post(url, data={"verify_user": "y", "submit_as_self": "y",
                                             "proxy_name": "Jane Proxy",
                                             "proxy_email": "jane.proxy@example.org",
                                             "action": "next", "csrf_token": token})
    assert resp.status_code == status.SEE_OTHER
    with app.app_context():
        submission, _ = app.api.get_with_history(sub_created.submission_id)
    assert submission.proxy is None
    assert submission.creator.email != "jane.proxy@example.org"
