"""The SWORD default-license page.

Ports ``arxiv-httpd/cgi-bin/sword_license.pl``. The assertions mirror
``arxiv-test-regression/pytest/tests/test_sword.py:27-52``
(``test_toggle_default_license``), which is part of the acceptance gate and matches
on exact HTML.
"""

import re

import arxiv.db.models as classic
from arxiv.db import Session

NONEXCLUSIVE = "http://arxiv.org/licenses/nonexclusive-distrib/1.0/"
CC0 = "http://creativecommons.org/publicdomain/zero/1.0/"

FORM = "application/x-www-form-urlencoded"

CSRF_FIELD = re.compile(rb'name="csrf_token"[^>]*?value="([^"]+)"')
"""WTForms renders the attributes alphabetically, so ``value`` follows ``name``."""


def _radio(value: str) -> bytes:
    """The exact markup the live suite greps for."""
    return (f'<input type="radio" name="License" value="{value}" '
            'checked="checked">').encode()


def _token(client) -> str:
    """A CSRF token from a freshly rendered page."""
    match = CSRF_FIELD.search(client.get("/sword-license").data)
    assert match is not None, "the page rendered no csrf_token field"
    return match.group(1).decode()


def _post(client, license_value: str, token=None):
    """POST a choice with a valid token unless one is supplied."""
    return client.post("/sword-license", data={
        "License": license_value,
        "csrf_token": _token(client) if token is None else token})


def _stored(app, session) -> object:
    """The license on file, or None.

    Rejection tests compare this before and after rather than asserting ``None``:
    the app fixture outlives a single test, so an earlier one may already have
    written a row, and "unchanged" is the property that actually matters.
    """
    with app.app_context():
        row = Session.get(classic.SwordLicense, int(session.user.user_id))
        return row.license if row is not None else None


# ------------------------------------------------------------------------- GET


def test_page_is_served(app, authorized_client):
    response = authorized_client.get("/sword-license")
    assert response.status_code == 200


def test_page_carries_the_sentence_the_live_suite_matches(app, authorized_client):
    """test_sword.py:36."""
    response = authorized_client.get("/sword-license")
    assert b"then SWORD deposits will be accepted" in response.data


def test_page_offers_every_current_license(app, authorized_client):
    response = authorized_client.get("/sword-license")
    for uri in (NONEXCLUSIVE, CC0):
        assert f'value="{uri}"'.encode() in response.data


def test_no_license_is_offered_too(app, authorized_client):
    response = authorized_client.get("/sword-license")
    assert b'value="no"' in response.data


def test_with_no_row_the_no_option_is_selected(app, authorized_client):
    """``get_sword_license`` returns ``$license || 'no'`` (sword_license.pl:88)."""
    response = authorized_client.get("/sword-license")
    assert _radio("no") in response.data


def test_page_requires_authentication(app):
    assert app.test_client().get("/sword-license").status_code == 401


# ------------------------------------------------------------------------ POST


def test_selecting_a_license_stores_it(app, authorized_client,
                                       authorized_user_session):
    session, _ = authorized_user_session
    response = _post(authorized_client, NONEXCLUSIVE)
    assert response.status_code == 200
    assert _radio(NONEXCLUSIVE) in response.data

    with app.app_context():
        row = Session.get(classic.SwordLicense, int(session.user.user_id))
        assert row is not None
        assert row.license == NONEXCLUSIVE
        assert row.updated is not None


def test_selecting_no_stores_the_literal_string(app, authorized_client,
                                                authorized_user_session):
    """sword_license.pl:96 stores ``'no'`` rather than clearing the row.

    The deposit gate then refuses it, because ``'no'`` is not a current license
    (``AtomPP.pm:1553``).
    """
    session, _ = authorized_user_session
    response = _post(authorized_client, "no")
    assert response.status_code == 200
    assert _radio("no") in response.data

    with app.app_context():
        row = Session.get(classic.SwordLicense, int(session.user.user_id))
        assert row.license == "no"


def test_toggling_replaces_the_previous_choice(app, authorized_client,
                                               authorized_user_session):
    """The whole shape of the live suite's test: off, then on."""
    session, _ = authorized_user_session

    off = _post(authorized_client, "no")
    assert _radio("no") in off.data

    on = _post(authorized_client, NONEXCLUSIVE)
    assert _radio(NONEXCLUSIVE) in on.data
    assert _radio("no") not in on.data

    with app.app_context():
        row = Session.get(classic.SwordLicense, int(session.user.user_id))
        assert row.license == NONEXCLUSIVE


def test_only_one_radio_is_checked(app, authorized_client):
    response = _post(authorized_client, CC0)
    assert response.data.count(b'checked="checked"') == 1


def test_a_license_that_is_not_offered_is_refused(app, authorized_client):
    """The Perl stored whatever arrived, with a bare ``# FIXME - check valid``."""
    response = _post(authorized_client, "http://example.org/made-up")
    assert response.status_code == 400


def test_a_missing_license_value_is_refused(app, authorized_client):
    response = authorized_client.post(
        "/sword-license", data={"csrf_token": _token(authorized_client)})
    assert response.status_code == 400


def test_post_requires_authentication(app):
    response = app.test_client().post("/sword-license", data="License=no",
                                      content_type=FORM)
    assert response.status_code == 401


# ------------------------------------------------------------------------ CSRF


def test_the_page_renders_a_csrf_token(app, authorized_client):
    assert CSRF_FIELD.search(authorized_client.get("/sword-license").data)


def test_post_without_a_token_is_refused(app, authorized_client,
                                         authorized_user_session):
    """The whole point: a cross-site form submission must not take effect.

    Setting a default license is a state change under cookie auth, so without this
    any page could make a logged-in depositor accept a license they did not choose,
    or select ``no`` and silently disable their deposits.
    """
    session, _ = authorized_user_session
    before = _stored(app, session)

    response = authorized_client.post("/sword-license",
                                      data=f"License={NONEXCLUSIVE}",
                                      content_type=FORM)
    assert response.status_code == 400
    assert _stored(app, session) == before, \
        "the license was written despite the missing token"


def test_post_with_a_forged_token_is_refused(app, authorized_client,
                                             authorized_user_session):
    session, _ = authorized_user_session
    before = _stored(app, session)

    response = _post(authorized_client, NONEXCLUSIVE,
                     token="deadbeef::2099-01-01T00:00:00.000000")
    assert response.status_code == 400
    assert _stored(app, session) == before


def test_post_with_a_malformed_token_is_refused(app, authorized_client):
    """No ``::`` separator, which `SessionCSRF` splits on unconditionally.

    Without the ValueError guard in the controller this is a 500 -- from input any
    client can send.
    """
    assert _post(authorized_client, NONEXCLUSIVE,
                 token="not-a-token").status_code == 400


def test_an_expired_token_is_refused(app, authorized_client,
                                     authorized_user_session):
    """``CSRFForm.Meta.csrf_timeout`` is 30 minutes; the expiry is in the token."""
    session, _ = authorized_user_session
    before = _stored(app, session)

    digest, _expires = _token(authorized_client).split("::", 1)
    expired = f"{digest}::2020-01-01T00:00:00.000000"

    assert _post(authorized_client, NONEXCLUSIVE,
                 token=expired).status_code == 400
    assert _stored(app, session) == before


def test_a_rejected_post_still_leaves_a_usable_page(app, authorized_client):
    """A fresh token must be issued, or the user is stuck after one failure."""
    authorized_client.post("/sword-license", data=f"License={CC0}",
                           content_type=FORM)
    assert _post(authorized_client, CC0).status_code == 200


def test_the_reissued_token_works_for_a_second_change(app, authorized_client,
                                                      authorized_user_session):
    """The token on the page returned by a successful POST must be valid.

    The controller rebuilds the form after saving rather than echoing the spent
    token back, so two changes in a row have to work.
    """
    session, _ = authorized_user_session
    first = _post(authorized_client, CC0)
    assert first.status_code == 200

    match = CSRF_FIELD.search(first.data)
    assert match is not None, "the response page carried no token"
    second = authorized_client.post("/sword-license", data={
        "License": NONEXCLUSIVE, "csrf_token": match.group(1).decode()})
    assert second.status_code == 200

    with app.app_context():
        row = Session.get(classic.SwordLicense, int(session.user.user_id))
        assert row.license == NONEXCLUSIVE
