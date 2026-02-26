"""Tests for :mod:`submit_ce.controllers.classification`."""

from submit_ce.api.domain.submission import Submission
from submit_ce.ui.tests import gets
from submit_ce.ui.tests.csrf_util import parse_csrf_token
 
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
