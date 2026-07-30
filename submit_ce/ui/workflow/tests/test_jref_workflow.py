"""Tests for the submission application as a whole."""
from http import HTTPStatus as status

from arxiv.db import models as classic
from arxiv.db import Session
from flask import current_app

from submit_ce.domain.agent import InternalClient
from submit_ce.domain.event import CreateSubmissionVersion
from submit_ce.ui.tests.csrf_util import parse_csrf_token


def _press_add_jref(client, paper_id):
    """Press the dashboard's "Add Journal Reference" button for a paper.

    The button is a POST form on the dashboard, so the token comes from there.
    """
    dashboard = client.get('/')
    assert dashboard.status_code == status.OK
    return client.post(f'/{paper_id}/add_jref',
                       data={'csrf_token': parse_csrf_token(dashboard)})


def _submit_jref_form(client, endpoint, doi, journal_ref, report_num):
    """Run the jref edit form's two-step preview-then-confirm flow."""
    response = client.get(endpoint)
    assert response.status_code == status.OK
    assert b'Journal reference' in response.data
    data = {'doi': doi, 'journal_ref': journal_ref, 'report_num': report_num,
            'csrf_token': parse_csrf_token(response)}

    # The first POST previews the updated abs page and asks for confirmation.
    response = client.post(endpoint, data=data)
    assert response.status_code == status.OK
    assert b'Confirm and Submit' in response.data

    # The second POST, confirmed, commits.
    data['confirmed'] = True
    data['csrf_token'] = parse_csrf_token(response)
    response = client.post(endpoint, data=data)
    assert response.status_code == status.SEE_OTHER
    return response


def test_create_jref_submission(app, authorized_client, published_submission):
    """A user adds a journal reference to an announced paper via the web UI."""
    submission, paper_id = published_submission

    # Creating the jref is keyed on the paper and sends the user to the new
    # jref's own edit page.
    response = _press_add_jref(authorized_client, paper_id)
    assert response.status_code == status.SEE_OTHER
    edit_endpoint = response.headers['Location']
    assert edit_endpoint.endswith('/jref')

    _submit_jref_form(authorized_client, edit_endpoint, '10.1000/182',
                      'foo journal 1992', 'abc report 42')

    with app.app_context():
        with Session() as session:
            rows = session.query(classic.Submission) \
                          .filter(classic.Submission.doc_paper_id == paper_id) \
                          .all()
            assert len(rows) == 2, "Creates a second row for the JREF"

            # The original announced row and the new jref row.
            orig = next(r for r in rows if r.type != 'jref')
            jref = next(r for r in rows if r.type == 'jref')

            # Identity: it is a jref row for the same document/paper, same version.
            assert jref.doc_paper_id == paper_id
            assert jref.document_id is not None
            assert jref.document_id == orig.document_id, \
                "jref shares the announced paper's document"
            assert jref.version == orig.version, "jref does not bump the version"
            assert jref.submission_id != orig.submission_id, \
                "jref is a distinct row"
            assert edit_endpoint.endswith(f'/{jref.submission_id}/jref')

            # The jref-specific fields carry the edited values.
            assert jref.doi == '10.1000/182'
            assert jref.journal_ref == 'foo journal 1992'
            assert jref.report_num == 'abc report 42'

            # The rest of the metadata is copied from the announced paper.
            assert jref.title == submission.metadata.title
            assert jref.abstract == submission.metadata.abstract
            assert jref.authors == submission.metadata.authors_display
            assert jref.comments == submission.metadata.comments


def test_jref_on_unannounced_submission(app, authorized_client, sub_created):
    """A jref cannot be made against something that is not an announced paper.

    The endpoint is keyed on a paper id, and an unannounced submission has none
    -- so a submission id here resolves to no document at all.
    """
    def jref_count():
        with app.app_context():
            with Session() as session:
                return session.query(classic.Submission) \
                              .filter(classic.Submission.type == 'jref') \
                              .count()

    before = jref_count()

    response = _press_add_jref(authorized_client, sub_created.submission_id)

    assert response.status_code == status.NOT_FOUND
    assert jref_count() == before, "No jref row for an unannounced submission"


def test_second_jref_edits_the_first(app, authorized_client,
                                     published_submission):
    """A paper accumulates journal-reference edits on a single jref row.

    A jref is its own submission, so the first press creates one and hands off
    to its edit page. Pressing the button again while that jref is still in
    progress returns there rather than starting a second one, so the paper still
    ends up with exactly one jref row carrying the latest values.
    """
    _, paper_id = published_submission

    response = _press_add_jref(authorized_client, paper_id)
    assert response.status_code == status.SEE_OTHER
    edit_endpoint = response.headers['Location']
    _submit_jref_form(authorized_client, edit_endpoint, '10.1000/182',
                      'foo journal 1992', 'abc report 42')

    # Pressing the button again returns to the jref already in progress.
    again = _press_add_jref(authorized_client, paper_id)
    assert again.status_code == status.SEE_OTHER
    assert again.headers['Location'] == edit_endpoint

    # Editing that jref updates it in place.
    _submit_jref_form(authorized_client, edit_endpoint, '10.2000/999',
                      'bar journal 2001', 'xyz report 77')

    with app.app_context():
        with Session() as session:
            rows = session.query(classic.Submission) \
                          .filter(classic.Submission.doc_paper_id == paper_id) \
                          .all()
            # Still just the original announced row plus a single jref row: the
            # second jref was absorbed into the first, not added as a new row.
            assert len(rows) == 2, \
                "Second jref is absorbed into the first jref row"

            jref_rows = [r for r in rows if r.type == 'jref']
            assert len(jref_rows) == 1
            jref = jref_rows[0]

            # The single jref row carries the values from the second edit.
            assert jref.doi == '10.2000/999'
            assert jref.journal_ref == 'bar journal 2001'
            assert jref.report_num == 'xyz report 77'


def test_jref_with_inprogress_replacement(app, authorized_user,
                                          authorized_client,
                                          published_submission):
    """A jref is rejected when the paper has an in-progress replacement.

    The guard lives in ``CreateJrefSubmission.validate_under_lock``. The user
    gets the explanatory page, no jref row is created, and the replacement is
    left untouched."""
    submission, paper_id = published_submission
    submission_id = submission.submission_id

    # Start a new version but do not submit it: an in-progress (WORKING) rep.
    with app.app_context():
        ua = InternalClient(name=f"test_client_{__file__}")
        current_app.api.save(
            CreateSubmissionVersion(creator=authorized_user, client=ua),
            submission_id=submission_id)

    # Capture the replacement row's jref-relevant fields before the jref, so we
    # can prove the jref leaves them untouched.
    with app.app_context():
        with Session() as session:
            rep_before = session.query(classic.Submission) \
                                .filter(classic.Submission.doc_paper_id == paper_id) \
                                .filter(classic.Submission.type == 'rep').one()
            rep_id = rep_before.submission_id
            rep_version = rep_before.version
            rep_doi = rep_before.doi
            rep_journal_ref = rep_before.journal_ref
            rep_report_num = rep_before.report_num

    response = _press_add_jref(authorized_client, paper_id)

    assert response.status_code == status.OK
    assert b'already has a submission in progress' in response.data

    with app.app_context():
        with Session() as session:
            rows = session.query(classic.Submission) \
                          .filter(classic.Submission.doc_paper_id == paper_id) \
                          .all()
            by_type = {r.type: r for r in rows}
            # No jref row was created: only the announced new row and the rep.
            assert set(by_type) == {'new', 'rep'}
            assert 'jref' not in by_type

            # The in-progress replacement is left completely untouched.
            rep = by_type['rep']
            assert rep.submission_id == rep_id
            assert rep.version == rep_version == by_type['new'].version + 1
            assert rep.status == 0
            assert rep.doi == rep_doi
            assert rep.journal_ref == rep_journal_ref
            assert rep.report_num == rep_report_num
