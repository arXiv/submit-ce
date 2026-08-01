"""The SWORD default-license page.

Ports ``arxiv-httpd/cgi-bin/sword_license.pl``. The assertions mirror
``arxiv-test-regression/pytest/tests/test_sword.py:27-52``
(``test_toggle_default_license``), which is part of the acceptance gate and matches
on exact HTML.
"""

import arxiv.db.models as classic
from arxiv.db import Session

NONEXCLUSIVE = "http://arxiv.org/licenses/nonexclusive-distrib/1.0/"
CC0 = "http://creativecommons.org/publicdomain/zero/1.0/"

FORM = "application/x-www-form-urlencoded"


def _radio(value: str) -> bytes:
    """The exact markup the live suite greps for."""
    return (f'<input type="radio" name="License" value="{value}" '
            'checked="checked">').encode()


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
    response = authorized_client.post("/sword-license",
                                      data=f"License={NONEXCLUSIVE}",
                                      content_type=FORM)
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
    response = authorized_client.post("/sword-license", data="License=no",
                                      content_type=FORM)
    assert response.status_code == 200
    assert _radio("no") in response.data

    with app.app_context():
        row = Session.get(classic.SwordLicense, int(session.user.user_id))
        assert row.license == "no"


def test_toggling_replaces_the_previous_choice(app, authorized_client,
                                               authorized_user_session):
    """The whole shape of the live suite's test: off, then on."""
    session, _ = authorized_user_session

    off = authorized_client.post("/sword-license", data="License=no",
                                 content_type=FORM)
    assert _radio("no") in off.data

    on = authorized_client.post("/sword-license", data=f"License={NONEXCLUSIVE}",
                                content_type=FORM)
    assert _radio(NONEXCLUSIVE) in on.data
    assert _radio("no") not in on.data

    with app.app_context():
        row = Session.get(classic.SwordLicense, int(session.user.user_id))
        assert row.license == NONEXCLUSIVE


def test_only_one_radio_is_checked(app, authorized_client):
    response = authorized_client.post("/sword-license", data=f"License={CC0}",
                                      content_type=FORM)
    assert response.data.count(b'checked="checked"') == 1


def test_a_license_that_is_not_offered_is_refused(app, authorized_client):
    """The Perl stored whatever arrived, with a bare ``# FIXME - check valid``."""
    response = authorized_client.post("/sword-license",
                                      data="License=http://example.org/made-up",
                                      content_type=FORM)
    assert response.status_code == 400


def test_a_missing_license_value_is_refused(app, authorized_client):
    response = authorized_client.post("/sword-license", data="",
                                      content_type=FORM)
    assert response.status_code == 400


def test_post_requires_authentication(app):
    response = app.test_client().post("/sword-license", data="License=no",
                                      content_type=FORM)
    assert response.status_code == 401
