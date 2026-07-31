"""Tests for the jref edit controller, ``GET|POST /<submission_id>/jref``.

`submission_id` is the *jref's own* id; creating one is `paper.add_jref`, and
covered by `ui/tests/test_add_jref.py`. The happy path -- prefilled form,
preview, confirm -- is covered end to end by
`ui/workflow/tests/test_jref_workflow.py`. These are the two rejection branches
that flow does not reach.
"""
from http import HTTPStatus as status

from submit_ce.ui.tests.csrf_util import parse_csrf_token


def _csrf_token(client, path='/'):
    response = client.get(path)
    assert response.status_code == status.OK
    return parse_csrf_token(response)


def _create_jref(client, paper_id):
    """Press the dashboard's Add Journal Reference button, return the jref path."""
    response = client.post(f'/{paper_id}/add_jref',
                           data={'csrf_token': _csrf_token(client)})
    assert response.status_code == status.SEE_OTHER
    return response.headers['Location']


def test_get_on_a_submission_that_is_not_a_jref(app, authorized_client,
                                                sub_created):
    """The endpoint edits a journal reference; it will not edit anything else.

    The id here is a plain working submission the user does own, so this is the
    type check rather than an authorization failure.
    """
    response = authorized_client.get(f'/{sub_created.submission_id}/jref')

    assert response.status_code == status.SEE_OTHER
    # Sent back to the dashboard, with a flash explaining why.
    assert response.headers['Location'].endswith('/')

    dashboard = authorized_client.get('/')
    assert b'not a journal reference submission' in dashboard.data


def test_post_without_csrf_token_is_rejected(app, authorized_client,
                                             published_submission):
    """A POST that fails form validation is a bad request, not a silent no-op."""
    _, paper_id = published_submission
    jref_path = _create_jref(authorized_client, paper_id)

    response = authorized_client.post(jref_path,
                                      data={'journal_ref': 'Nucl.Phys. B1'})

    assert response.status_code == status.BAD_REQUEST

    # Control: the same POST with a token is accepted (and asks the user to
    # confirm), so it is the missing token that made the difference.
    with_token = authorized_client.post(
        jref_path, data={'journal_ref': 'Nucl.Phys. B1',
                         'csrf_token': _csrf_token(authorized_client,
                                                   jref_path)})
    assert with_token.status_code == status.OK
