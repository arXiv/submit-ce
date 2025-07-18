"""Tests for :mod:`submit_ce.controllers.classification`."""

from submit_ce.api.domain.submission import Submission
from submit_ce.ui.tests import gets
from submit_ce.ui.tests.csrf_util import parse_csrf_token
 

def test_primary_classification(app, authorized_client, sub_policy):
    sub: Submission = sub_policy
    assert sub and not sub.primary_classification

    url = "/9929929292/classification"
    resp = authorized_client.get(url)
    assert resp.status_code == 404

    url = f"/{sub.submission_id}/classification"
    resp = authorized_client.get(url)
    assert resp.status_code == 200 and b"Choose a Primary Category" in resp.data and b"<form " in resp.data

    resp = authorized_client.post(url, data={})
    assert resp.status_code == 400 and b"Choose a Primary Category" in resp.data and b"<form " in resp.data
    resp = authorized_client.post(url, data={'csrf_token':parse_csrf_token(resp)})
    assert resp.status_code == 400 and b"Choose a Primary Category" in resp.data and b"<form " in resp.data

    #tests unendorsed
    resp = authorized_client.post(url, data={'csrf_token':parse_csrf_token(resp), 'category':'math.GR'})
    assert resp.status_code == 400 and b"Choose a Primary Category" in resp.data and b"<form " in resp.data

    resp = authorized_client.post(url, data={'csrf_token':parse_csrf_token(resp), 'category':'astro-ph.CO'})
    assert resp.status_code == 200 and b"Choose a Primary Category" in resp.data and b"<form " in resp.data
    assert gets(app,sub).primary_classification and gets(app,sub).primary_classification.id == "astro-ph.CO"


def test_cross_classification(app, authorized_client, sub_policy):
    sub: Submission = sub_policy
    assert sub and not sub.primary_classification

    assert authorized_client.get("/9929929292/cross_list").status_code == 404

    # # must do primary before cross
    cross_url = f"/{sub.submission_id}/cross_list"
    resp = authorized_client.get(cross_url)
    assert resp.status_code == 303 and resp.headers["Location"] == f"/{sub.submission_id}/classification"

    # do primary so we can get to cross
    primary_url=f"/{sub.submission_id}/classification"
    resp = authorized_client.get(primary_url)
    resp = authorized_client.post(primary_url, data={'csrf_token':parse_csrf_token(resp),
                                                     'action':'next',
                                                     'category':'astro-ph.CO'})
    assert resp.status_code == 303 and resp.headers["Location"] == cross_url
    assert gets(app,sub).primary_classification and gets(app,sub).primary_classification.id == "astro-ph.CO"

    # now client can get the cross form
    cross_url = f"/{sub.submission_id}/cross_list"
    resp = authorized_client.get(cross_url)
    assert resp.status_code == 200 and b"<title>Choose Cross-List" in resp.data and b"<form " in resp.data
    
    # attempt some bad data    
    resp = authorized_client.post(cross_url, data={})
    assert resp.status_code == 400 and b"<title>Choose Cross-List" in resp.data and b"<form " in resp.data
    resp = authorized_client.post(cross_url, data={'csrf_token':parse_csrf_token(resp)})
    assert resp.status_code == 400 and b"<title>Choose Cross-List" in resp.data and b"<form " in resp.data

    #tests unendorsed
    resp = authorized_client.post(cross_url, data={'csrf_token':parse_csrf_token(resp), 'category':'math.GR'})
    assert resp.status_code == 400 and b"<title>Choose Cross-List" in resp.data and b"<form " in resp.data

    # invalid due to cross to primary
    resp = authorized_client.post(cross_url, data={'csrf_token':parse_csrf_token(resp), 'category':'astro-ph.CO'})
    assert resp.status_code == 400 and b"<title>Choose Cross-List" in resp.data and b"<form " in resp.data
    assert gets(app,sub).primary_classification and gets(app,sub).primary_classification.id == "astro-ph.CO"
