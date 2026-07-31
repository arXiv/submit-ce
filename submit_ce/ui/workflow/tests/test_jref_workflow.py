"""Tests for the submission application as a whole."""
from http import HTTPStatus as status

from arxiv.db import models as classic
from arxiv.db import Session
from flask import current_app

from submit_ce.domain.agent import InternalClient
from submit_ce.domain.event import CreateSubmissionVersion, \
    EmailSubmitterFinalizeMsg, FinalizeJrefSubmission
from submit_ce.implementations.legacy_implementation.models import \
    Submission as LegacyRow
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

            # Confirming submits it for announcement. Without this the row sits
            # at WORKING and the publish pipeline never sees it, however
            # complete its metadata is.
            assert jref.status == LegacyRow.SUBMITTED, \
                "Confirm and Submit must finalize the jref"
            assert jref.submit_time is not None

            # The announced row is not dragged along with it.
            assert orig.status == LegacyRow.ANNOUNCED

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


def test_a_submitted_jref_is_not_edited_again(app, authorized_client,
                                              published_submission):
    """A jref is submitted once, and a paper never gets a second one.

    A submitted jref is still `is_active`, so pressing Add Journal Reference
    again resumes to it rather than starting a second one -- and its edit page
    then sends the user back to the dashboard instead of offering a form that
    `SetJournalReference` would reject.
    """
    _, paper_id = published_submission

    response = _press_add_jref(authorized_client, paper_id)
    assert response.status_code == status.SEE_OTHER
    edit_endpoint = response.headers['Location']
    _submit_jref_form(authorized_client, edit_endpoint, '10.1000/182',
                      'foo journal 1992', 'abc report 42')

    # Pressing the button again resumes to the same jref, without creating one.
    again = _press_add_jref(authorized_client, paper_id)
    assert again.status_code == status.SEE_OTHER
    assert again.headers['Location'] == edit_endpoint

    # Its edit page is closed now that it has been submitted.
    reopened = authorized_client.get(edit_endpoint)
    assert reopened.status_code == status.SEE_OTHER
    dashboard = authorized_client.get(reopened.headers['Location'])
    assert b'already been submitted' in dashboard.data

    # A confirmed POST does not slip past the redirect either.
    resubmit = authorized_client.post(
        edit_endpoint, data={'doi': '10.2000/999',
                             'journal_ref': 'bar journal 2001',
                             'report_num': 'xyz report 77',
                             'confirmed': True,
                             'csrf_token': parse_csrf_token(dashboard)})
    assert resubmit.status_code == status.SEE_OTHER

    with app.app_context():
        with Session() as session:
            rows = session.query(classic.Submission) \
                          .filter(classic.Submission.doc_paper_id == paper_id) \
                          .all()
            # The announced row plus exactly one jref row.
            assert len(rows) == 2

            jref_rows = [r for r in rows if r.type == 'jref']
            assert len(jref_rows) == 1
            jref = jref_rows[0]

            # Still carrying the submitted values, not the rejected edit.
            assert jref.status == LegacyRow.SUBMITTED
            assert jref.doi == '10.1000/182'
            assert jref.journal_ref == 'foo journal 1992'
            assert jref.report_num == 'abc report 42'


def test_submitting_emails_the_submitter(app, authorized_client,
                                         published_submission):
    """Submitting through the UI sends the one confirmation mail, and no more.

    The email is a consequence of `FinalizeJrefSubmission`, so it is also
    evidence that the finalize actually ran.
    """
    _, paper_id = published_submission

    edit_endpoint = _press_add_jref(authorized_client,
                                    paper_id).headers['Location']
    with app.app_context():
        before = len(current_app.api.email_service.sent)

    _submit_jref_form(authorized_client, edit_endpoint, '10.1000/182',
                      'foo journal 1992', 'abc report 42')

    with app.app_context():
        service = current_app.api.email_service
        assert len(service.sent) == before + 1, \
            "Exactly one mail: no moderator notification for a jref"
        assert service.last.subject == f"arXiv journal ref for {paper_id}"

        # And it is recorded in the jref's own history, having been sent.
        submission_id = edit_endpoint.rstrip('/').split('/')[-2]
        _, history = current_app.api.get_with_history(submission_id)
        assert len([e for e in history
                    if isinstance(e, FinalizeJrefSubmission)]) == 1
        emails = [e for e in history
                  if isinstance(e, EmailSubmitterFinalizeMsg)]
        assert len(emails) == 1
        assert emails[0].error is None


def test_confirming_with_no_changes_does_not_submit(app, authorized_client,
                                                   published_submission):
    """Nothing changed means nothing to announce, so the jref is not submitted.

    A jref is seeded from the announced paper, so its citation fields can
    already be populated when the form first opens. Confirming that unchanged
    form must not fire an empty announcement.
    """
    _, paper_id = published_submission

    edit_endpoint = _press_add_jref(authorized_client,
                                    paper_id).headers['Location']

    page = authorized_client.get(edit_endpoint)
    assert page.status_code == status.OK
    # Post the form back exactly as rendered, already confirmed.
    response = authorized_client.post(
        edit_endpoint, data={'doi': '', 'journal_ref': '', 'report_num': '',
                             'confirmed': True,
                             'csrf_token': parse_csrf_token(page)})

    assert response.status_code == status.OK
    assert b'No changes to submit' in response.data

    with app.app_context():
        with Session() as session:
            jref = session.query(classic.Submission) \
                          .filter(classic.Submission.doc_paper_id == paper_id) \
                          .filter(classic.Submission.type == 'jref').one()
        assert jref.status == LegacyRow.WORKING
        assert jref.submit_time is None

        submission_id = edit_endpoint.rstrip('/').split('/')[-2]
        _, history = current_app.api.get_with_history(submission_id)
        assert not [e for e in history
                    if isinstance(e, FinalizeJrefSubmission)]


def test_an_invalid_value_submits_nothing(app, authorized_client,
                                          published_submission):
    """The values and the submit land together, or neither does.

    The `Set*` events and `FinalizeJrefSubmission` go in one `save`, so a
    rejected value must not leave a jref that is submitted, or one carrying
    half the edit.
    """
    _, paper_id = published_submission

    edit_endpoint = _press_add_jref(authorized_client,
                                    paper_id).headers['Location']
    page = authorized_client.get(edit_endpoint)

    response = authorized_client.post(
        edit_endpoint,
        data={'doi': 'not-a-doi', 'journal_ref': 'foo journal 1992',
              'report_num': 'abc report 42', 'confirmed': True,
              'csrf_token': parse_csrf_token(page)})

    assert response.status_code == status.BAD_REQUEST

    with app.app_context():
        with Session() as session:
            jref = session.query(classic.Submission) \
                          .filter(classic.Submission.doc_paper_id == paper_id) \
                          .filter(classic.Submission.type == 'jref').one()
        # Not submitted, and the good values did not land either.
        assert jref.status == LegacyRow.WORKING
        assert jref.submit_time is None
        assert jref.journal_ref in (None, '')
        assert jref.doi in (None, '')


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
