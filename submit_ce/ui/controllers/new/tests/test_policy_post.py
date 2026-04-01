# submit_ce/ui/controllers/tests/test_policy_post.py

from flask import current_app
from sqlalchemy import text
from arxiv.db import Session
from submit_ce.ui.tests.csrf_util import parse_csrf_token

from flask import current_app
from sqlalchemy import text
from arxiv.db import Session
from submit_ce.ui.tests.csrf_util import parse_csrf_token


def test_policy_post_sets_agreement_id(app, authorized_client, sub_authorship):
    """
    Ensure a valid POST to /<sid>/policy:
    - Accepts the current policy ID (3)
    - Creates ConfirmPolicy with agreement_id=3
    - Persists agree_policy=1 and agreement_id=3 into classic DB
    - Returns HTTP 200 (ready_for_next)
    """

    sid = sub_authorship.submission_id
    policy_id = 3

    with app.app_context():
        # STEP 1: GET form to extract CSRF token
        get_resp = authorized_client.get(f"/{sid}/policy")
        assert get_resp.status_code == 200

        csrf = parse_csrf_token(get_resp)

        # STEP 2: POST valid policy acceptance
        post_resp = authorized_client.post(
            f"/{sid}/policy",
            data={
                "csrf_token": csrf,
                "policy_id": policy_id,
                "policy": "y"
            }
        )

        # Controller returns 200 OK on success (not a redirect)
        assert post_resp.status_code == 200

        # STEP 3: Check DB
        row = Session.execute(
            text("""
                SELECT agree_policy, agreement_id
                FROM arXiv_submissions
                WHERE submission_id = :sid
            """),
            {"sid": sid}
        ).fetchone()

        assert row is not None, "Submission row should exist"
        assert row.agree_policy == 1
        assert row.agreement_id == policy_id


def test_policy_round_trip_after_accept(app, authorized_client, sub_authorship):
    """
    After accepting the policy:
    - A subsequent GET should show policy pre-checked
    - Database should contain updated agreement_id and agree_policy
    """
    sid = sub_authorship.submission_id
    policy_id = 3

    with app.app_context():
        # 1. GET to retrieve CSRF token
        get_resp = authorized_client.get(f"/{sid}/policy")
        assert get_resp.status_code == 200

        csrf = parse_csrf_token(get_resp)

        # 2. POST to accept policy
        post_resp = authorized_client.post(
            f"/{sid}/policy",
            data={
                "csrf_token": csrf,
                "policy_id": policy_id,
                "policy": "y",
            }
        )
        assert post_resp.status_code == 200

        # 3. GET again; policy must now show as accepted
        get2 = authorized_client.get(f"/{sid}/policy")
        assert get2.status_code == 200
        assert b'checked' in get2.data or b'value="y"' in get2.data

        # 4. Confirm DB row updated
        row = Session.execute(
            text("""
                SELECT agree_policy, agreement_id
                FROM arXiv_submissions
                WHERE submission_id = :sid
            """),
            {"sid": sid}
        ).fetchone()

        assert row.agree_policy == 1
        assert row.agreement_id == policy_id


def test_policy_post_wrong_policy_id(app, authorized_client, sub_authorship):
    """
    POST fails (400) if policy_id does not match current_policy_id=3.
    """
    sid = sub_authorship.submission_id

    with app.app_context():
        get_resp = authorized_client.get(f"/{sid}/policy")
        assert get_resp.status_code == 200
        csrf = parse_csrf_token(get_resp)

        resp = authorized_client.post(
            f"/{sid}/policy",
            data={"csrf_token": csrf, "policy_id": 99, "policy": "y"}
        )
        assert resp.status_code == 400


def test_policy_post_missing_policy_checkbox(app, authorized_client, sub_authorship):
    """
    POST fails (400) if 'policy' checkbox ("y") is missing.
    """
    sid = sub_authorship.submission_id

    with app.app_context():
        get_resp = authorized_client.get(f"/{sid}/policy")
        csrf = parse_csrf_token(get_resp)

        resp = authorized_client.post(
            f"/{sid}/policy",
            data={"csrf_token": csrf, "policy_id": 3}  # missing "policy"
        )
        assert resp.status_code == 400


def test_policy_post_missing_policy_id(app, authorized_client, sub_authorship):
    """
    POST fails (400) if 'policy_id' is missing.
    """
    sid = sub_authorship.submission_id

    with app.app_context():
        get_resp = authorized_client.get(f"/{sid}/policy")
        csrf = parse_csrf_token(get_resp)

        resp = authorized_client.post(
            f"/{sid}/policy",
            data={"csrf_token": csrf, "policy": "y"}  # missing policy_id
        )
        assert resp.status_code == 400


def test_policy_post_unexpected_extra_field(app, authorized_client, sub_authorship):
    """
    POST fails (400) if unexpected form fields are included.
    """
    sid = sub_authorship.submission_id

    with app.app_context():
        get_resp = authorized_client.get(f"/{sid}/policy")
        csrf = parse_csrf_token(get_resp)

        resp = authorized_client.post(
            f"/{sid}/policy",
            data={
                "csrf_token": csrf,
                "policy_id": 3,
                "policy": "y",
                "evil": "not-allowed"
            }
        )
        assert resp.status_code == 400


def test_policy_cannot_unaccept_after_accepting(app, authorized_client, sub_authorship):
    """
    Once the policy is accepted, the user cannot unaccept it.
    POST with policy="n" must return 400.
    """
    sid = sub_authorship.submission_id

    with app.app_context():
        # Accept policy first
        get_resp = authorized_client.get(f"/{sid}/policy")
        csrf = parse_csrf_token(get_resp)

        authorized_client.post(
            f"/{sid}/policy",
            data={"csrf_token": csrf, "policy_id": 3, "policy": "y"}
        )

        # Try to unaccept
        get_resp2 = authorized_client.get(f"/{sid}/policy")
        csrf2 = parse_csrf_token(get_resp2)

        resp = authorized_client.post(
            f"/{sid}/policy",
            data={"csrf_token": csrf2, "policy_id": 3, "policy": "n"}
        )
        assert resp.status_code == 400


def test_policy_accept_advances_workflow(app, authorized_client, sub_authorship):
    """
    After accepting policy:
    - ready_for_next() is invoked
    - submission reflects submitter_accepts_policy=True
    """
    sid = sub_authorship.submission_id

    with app.app_context():
        get_resp = authorized_client.get(f"/{sid}/policy")
        csrf = parse_csrf_token(get_resp)

        resp = authorized_client.post(
            f"/{sid}/policy",
            data={"csrf_token": csrf, "policy_id": 3, "policy": "y"},
            follow_redirects=True
        )

        assert resp.status_code == 200
        # Workflow advanced: submission now has submitter_accepts_policy=True
        submission = current_app.api.get(str(sid))
        assert submission.submitter_accepts_policy is True
