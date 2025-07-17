"""Tests for the submission application as a whole."""

from http import HTTPStatus as status
from urllib.parse import urlparse
from submit_ce.ui import backend
from submit_ce.ui.tests.csrf_util import parse_csrf_token


# TODO: finish building out this test suite. The current tests run up to
# file upload. Once the remaining stages have stabilized, this should have
# tests for the whole submit process.

def _parse_csrf_token(response):
    try:
        return parse_csrf_token(response)
    except AttributeError:
        raise RuntimeError('Could not find CSRF token')

def test_create_submission(app, authorized_client, mocker):
    """User creates a new submission, and proceeds up to upload stage."""
    client = authorized_client

    # Get the home page of the submit system.
    response = client.get('/')
    assert status.OK ==  response.status_code
    assert response.content_type ==  'text/html; charset=utf-8'

    # Create a submission.
    response = client.post('/',data={'new': 'new', 'csrf_token': _parse_csrf_token(response)})
    assert response.status_code ==  status.SEE_OTHER

    # Get the next page in the process. This should be the verify_user stage.
    next_page = urlparse(response.headers['Location'])
    
    assert 'verify_user' in next_page.path
    response = client.get(next_page.path)
    assert b'By checking this box, I verify that my user information is correct.' in response.data
    sub_id, _ = next_page.path.lstrip('/').split('/verify_user', 1)
    def _sub():
        with app.app_context():
            from flask import current_app
            return current_app.api.get(sub_id)
    assert _sub()
    
    token = _parse_csrf_token(response)

    response = client.get(f'/{sub_id}/file_upload')
    assert response.status_code in [ status.FOUND, status.SEE_OTHER ], "disallow skip forward"
    response = client.get(f'/{sub_id}/final_preview')
    assert response.status_code in [ status.FOUND, status.SEE_OTHER ], "disallow skip forward"
    response = client.get(f'/{sub_id}/add_optional_metadata')
    assert response.status_code in [ status.FOUND, status.SEE_OTHER ], "disallow skip forward"

    # Submit the verify user page.
    response = client.post(next_page.path, data={'verify_user': 'y',
                                                 'action': 'next',
                                                 'csrf_token': token})
    assert response.status_code == status.SEE_OTHER

    # Get the next page in the process. This is the authorship stage.
    next_page = urlparse(response.headers['Location'])
    assert 'authorship' in  next_page.path
    response = client.get(next_page.path)
    assert response.status_code == status.OK
    assert 'I am an author of this paper' in response.text

    # Submit the authorship page.
    response = client.post(next_page.path, data={'authorship': 'y',
                                                 'action': 'next',
                                                 'csrf_token': _parse_csrf_token(response)})
    assert response.status_code == status.SEE_OTHER

    # Get the next page in the process. This is the license stage.
    next_page = urlparse(response.headers['Location'])
    assert 'license' in next_page.path
    response = client.get(next_page.path)
    assert b'Select a License' in response.data

    # Submit the license page.
    selected = "http://creativecommons.org/licenses/by-sa/4.0/"
    response = client.post(next_page.path, data={'license': selected,
                                                 'action': 'next',
                                                 'csrf_token': _parse_csrf_token(response)})
    assert response.status_code ==  status.SEE_OTHER

    # Get the next page in the process. This is the policy stage.
    next_page = urlparse(response.headers['Location'])
    assert 'policy' in next_page.path
    response = client.get(next_page.path)
    assert b'By checking this box, I agree to the policies listed on this page'  in response.data

    # Submit the policy page.
    response = client.post(next_page.path, data={'policy': 'y',
                                                 'policy_id': 3,
                                                 'action': 'next',
                                                 'csrf_token': _parse_csrf_token(response)})
    assert response.status_code in [ status.FOUND, status.SEE_OTHER ]

    # Get the next page in the process. This is the primary category stage.
    next_page = urlparse(response.headers['Location'])
    assert 'classification' in next_page.path

    # GET primary page
    response = client.get(next_page.path)
    assert b'Choose a Primary Classification' in response.data \
        and response.status_code == status.OK

    # POST the primary category page.
    response = client.post(next_page.path,data={'category': 'astro-ph.GA',
                                                'action': 'next',
                                                'csrf_token': _parse_csrf_token(response)})
    assert response.status_code in [ status.FOUND, status.SEE_OTHER ] \
        and response.status_code != status.BAD_REQUEST

    assert _sub().primary_category == 'astro-ph.GA'
    # GET the next page in the process. This is the cross list stage.
    next_page = urlparse(response.headers['Location'])
    assert 'cross' in next_page.path

    response = client.get(next_page.path)
    assert response.status_code == 200 # if 302 or 303 likely primary form didn't work
    assert b'Choose Cross-List Classifications' in response.data

    # Submit the cross-list category page.
    response = client.post(next_page.path,
                                data={'category': 'astro-ph.CO',
                                      'csrf_token': _parse_csrf_token(response)})
    assert response.status_code ==  status.OK

    response = client.post(next_page.path,
                                data={'action': 'next'})
    assert response.status_code ==  status.SEE_OTHER

    # Get the next page in the process. This is the file upload stage.
    next_page = urlparse(response.headers['Location'])
    assert 'upload' in next_page.path
    response = client.get(next_page.path)
    assert b'Upload Files' in response.data
    token = _parse_csrf_token(response)

