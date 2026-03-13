"""Tests for :mod:`submit_ce.controllers.license`."""
import re
import pytest
from arxiv.license import LICENSES


def _extract_csrf(html_bytes: bytes) -> str:
    # Adjust to your CSRF field name; typical hidden input name is "csrf_token"
    m = re.search(rb'name="csrf_token" value="([^"]+)"', html_bytes)
    return m.group(1).decode() if m else ""

@pytest.mark.usefixtures("app")
def test_license_post_no_change_advances(authorized_client, sub_policy):
    """
    When the user submits the same license choice that the submission already has,
    the controller should treat it as a no-op and move to the next stage
    (ready_for_next), returning 200 without error.
    """
    sub = sub_policy

    # Add a license
    first_uri = next(iter(LICENSES.keys()))
    sub.license = type("L", (), {"uri": first_uri})

    assert sub.license and sub.license.uri, "Fixture must provide an existing license URI"

    # 1) GET the license form (captures CSRF if enabled)
    get_url = f"/{sub.submission_id}/license"
    get_resp = authorized_client.get(get_url)
    assert get_resp.status_code == 200
    csrf_token = _extract_csrf(get_resp.data)

    # 2) POST the *same* license value (no-op)
    post_data = {
        "license": sub.license.uri,    # same as current license
    }
    if csrf_token:
        post_data["csrf_token"] = csrf_token

    post_resp = authorized_client.post(get_url, data=post_data, follow_redirects=False)

    # Expected: controller returns a 200 OK and advances via ready_for_next
    assert post_resp.status_code == 200
