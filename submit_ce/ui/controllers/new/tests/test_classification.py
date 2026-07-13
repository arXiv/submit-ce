"""Tests for :mod:`submit_ce.controllers.classification`."""

import arxiv.db.models as classic
from arxiv.db import Session

from submit_ce.domain.submission import Submission
from submit_ce.ui.tests import gets
from submit_ce.ui.tests.csrf_util import parse_csrf_token


def _endorse(app, user, *categories):
    """Add auto endorsements so the fixture user can pick these categories."""
    with app.app_context():
        for cat in categories:
            archive, _, subject = cat.partition(".")
            Session.add(classic.Endorsement(
                endorsee_id=user.user_id, archive=archive, subject_class=subject,
                flag_valid=1, type="auto", point_value=10,
                issued_when=11074371513))
        Session.commit()


primary_page_title=b"Suggest Category"
def test_primary_classification(app, authorized_client, sub_license):
    sub: Submission = sub_license
    assert sub and not sub.primary_classification

    url = "/9929929292/classification"
    resp = authorized_client.get(url)
    assert resp.status_code == 404

    url = f"/{sub.submission_id}/classification"
    resp = authorized_client.get(url)
    assert resp.status_code == 200 and primary_page_title in resp.data and b"<form " in resp.data

    resp = authorized_client.post(url, data={})
    assert resp.status_code == 400 and primary_page_title in resp.data and b"<form " in resp.data
    resp = authorized_client.post(url, data={'csrf_token':parse_csrf_token(resp)})
    assert resp.status_code == 400 and primary_page_title in resp.data and b"<form " in resp.data

    #tests unendorsed
    resp = authorized_client.post(url, data={'csrf_token':parse_csrf_token(resp), 'primary':'math.GR'})
    assert resp.status_code == 400 and primary_page_title in resp.data and b"<form " in resp.data

    assert not gets(app,sub).primary_classification or gets(app,sub).primary_classification.id != "astro-ph.CO"
    resp = authorized_client.post(url, data={'csrf_token':parse_csrf_token(resp), 'primary':'astro-ph.CO', 'action':'next'})
    assert resp.status_code == 303
    assert gets(app,sub).primary_classification and gets(app,sub).primary_classification.id == "astro-ph.CO"

    # invalid due to cross to primary
    resp = authorized_client.get(url)
    resp = authorized_client.post(url, data={'csrf_token':parse_csrf_token(resp),
                                             'primary':'astro-ph.CO',
                                             'staged_add':'astro-ph.CO'})
    assert resp.status_code == 400 and primary_page_title in resp.data and b"<form " in resp.data
    assert gets(app,sub).primary_classification and gets(app,sub).primary_classification.id == "astro-ph.CO"

    resp = authorized_client.get(url)
    resp = authorized_client.post(url, data={'csrf_token':parse_csrf_token(resp),
                                             'primary':'astro-ph.CO',
                                             'secondaries_staged_add':'astro-ph.GA',
                                             'action': 'next'})
    assert resp.status_code == 303 and "file_upload" in resp.headers["Location"]
    assert gets(app,sub).primary_classification and gets(app,sub).primary_classification.id == "astro-ph.CO"
    assert gets(app,sub).secondary_classification and gets(app,sub).secondary_classification[0].id == "astro-ph.GA"


def test_change_general_primary_to_specific(app, authorized_client, authorized_user, sub_license):
    """SUBMISSION-158 regression: after saving a general primary (cs.OH),
    changing it to a non-general primary (cs.HC) must save and advance,
    not lose the value and bounce back to the classification stage."""
    sub = sub_license
    _endorse(app, authorized_user, "cs.OH", "cs.HC")
    url = f"/{sub.submission_id}/classification"

    # Save a general primary.
    resp = authorized_client.get(url)
    resp = authorized_client.post(url, data={'csrf_token': parse_csrf_token(resp),
                                             'primary': 'cs.OH', 'action': 'next'})
    assert resp.status_code == 303
    assert gets(app, sub).primary_classification.id == "cs.OH"

    # Change it to a non-general primary and continue.
    resp = authorized_client.get(url)
    resp = authorized_client.post(url, data={'csrf_token': parse_csrf_token(resp),
                                             'primary': 'cs.HC', 'action': 'next'})
    assert resp.status_code == 303, resp.data
    assert gets(app, sub).primary_classification.id == "cs.HC"


def test_general_primary_drops_secondary_and_stays(app, authorized_client, authorized_user, sub_license):
    """SUBMISSION-158: saving primary=cs.HC + secondary=cs.DB, then changing
    the primary to a general category (cs.OH), must NOT advance to upload with
    the secondary intact. The secondary is dropped and the user stays on the
    classification page; switching back to cs.HC does not bring cs.DB back."""
    sub = sub_license
    _endorse(app, authorized_user, "cs.OH", "cs.HC", "cs.DB")
    url = f"/{sub.submission_id}/classification"

    # Save a non-general primary with a secondary.
    resp = authorized_client.get(url)
    resp = authorized_client.post(url, data={'csrf_token': parse_csrf_token(resp),
                                             'primary': 'cs.HC',
                                             'secondaries_staged_add': 'cs.DB',
                                             'action': 'next'})
    assert resp.status_code == 303
    saved = gets(app, sub)
    assert saved.primary_classification.id == "cs.HC"
    assert saved.secondary_categories == ["cs.DB"]

    # Change primary to a general category: must stay on classification (200,
    # not a 303 to file_upload) and drop the secondary.
    resp = authorized_client.get(url)
    resp = authorized_client.post(url, data={'csrf_token': parse_csrf_token(resp),
                                             'primary': 'cs.OH',
                                             'action': 'next'})
    assert resp.status_code == 200
    assert b"not allowed with a general" in resp.data
    saved = gets(app, sub)
    assert saved.primary_classification.id == "cs.OH"
    assert saved.secondary_categories == []

    # Switching the primary back to cs.HC must not resurrect cs.DB.
    resp = authorized_client.get(url)
    resp = authorized_client.post(url, data={'csrf_token': parse_csrf_token(resp),
                                             'primary': 'cs.HC',
                                             'action': 'next'})
    assert resp.status_code == 303
    saved = gets(app, sub)
    assert saved.primary_classification.id == "cs.HC"
    assert saved.secondary_categories == []


def test_crosslist_offered_for_non_general_primary(app, authorized_client, sub_primary):
    """SUBMISSION-158 UI gate: a non-general primary (astro-ph.GA) still offers
    cross-lists. The 'not available' note must not appear."""
    sub = sub_primary
    resp = authorized_client.get(f"/{sub.submission_id}/classification")
    assert resp.status_code == 200
    assert b'id="combobox"' in resp.data
    assert b"not available because the primary category" not in resp.data
