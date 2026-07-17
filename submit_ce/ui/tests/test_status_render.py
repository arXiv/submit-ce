"""Smoke test that the status page renders its event list."""
from http import HTTPStatus as status


def test_status_page_renders(admin_client, sub_license):
    client = admin_client
    response = client.get(f'/debug/{sub_license.submission_id}')
    assert response.status_code == status.OK
    body = response.data.decode('utf-8')
    # Header and collapsible sections should be present.
    assert 'Events' in body
    assert 'Creator:' in body
    assert 'Client:' in body
    # Client name from the InternalClient used in fixtures.
    assert 'test_client_' in body
    # "as json" link + shared modal for viewing raw event JSON.
    assert 'event-json-link' in body
    assert 'id="event-json-modal"' in body
    # Structured Submission section with agent + metadata sub-sections.
    assert 'Submission' in body
    assert 'Owner:' in body
    assert 'Metadata' in body
