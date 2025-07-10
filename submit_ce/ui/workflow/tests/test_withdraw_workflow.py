"""Tests for the submission application as a whole."""

import os
import tempfile
from http import HTTPStatus as status

from arxiv.db import Session
import arxiv.db.models as classic

from arxiv.auth.auth import scopes
from arxiv.auth.helpers import generate_token

from submit_ce.api.domain import Author, SubmissionContent
from submit_ce.api.domain import User
from submit_ce.api.domain.agent import InternalClient
from submit_ce.api.domain.event import SetPrimaryClassification, CreateSubmission, ConfirmContactInformation, \
    ConfirmAuthorship, SetLicense, ConfirmPolicy, SetUploadPackage, SetTitle, SetAbstract, SetComments, SetReportNumber, \
    SetAuthors, FinalizeSubmission
from submit_ce.ui import backend
from submit_ce.ui.backend import api
from submit_ce.ui.tests.csrf_util import parse_csrf_token

def test_withdrawl_workflow(app, authorized_user_session, authorized_client, authorized_user):
    """Tests that progress through the withdrawal request workflow."""
    session, jwt = authorized_user_session
    client = authorized_client
    user = authorized_user
    ua = InternalClient(name=f"test_client_{__file__}")
    # def setUp(self):
    #     """Create an application instance."""
    #     self.app = create_ui_web_app()
    #     os.environ['JWT_SECRET'] = str(self.app.config.get('JWT_SECRET', 'fo'))
    #     _, self.db = tempfile.mkstemp(suffix='.db')
    #     self.app.config['CLASSIC_DATABASE_URI'] = f'sqlite:///{self.db}'
    #     self.user = User('1234', 'foo@bar.com',
    #                      endorsements=['astro-ph.GA', 'astro-ph.CO'])
    #     self.token = generate_token('1234', 'foo@bar.com', 'foouser',
    #                                 scope=[scopes.CREATE_SUBMISSION,
    #                                        scopes.EDIT_SUBMISSION,
    #                                        scopes.VIEW_SUBMISSION,
    #                                        scopes.READ_UPLOAD,
    #                                        scopes.WRITE_UPLOAD,
    #                                        scopes.DELETE_UPLOAD_FILE],
    #                                 endorsements=[
    #                                     'astro-ph.GA',
    #                                     'astro-ph.CO',
    #                                 ])
    #     self.headers = {'Authorization': self.token}
    #     self.client = self.app.test_client()

    # Create and announce a submission.
    with app.app_context():
        cc0 = 'http://creativecommons.org/publicdomain/zero/1.0/'
        submission, _ = api.save(
            CreateSubmission(creator=user, client=ua),
            ConfirmContactInformation(creator=user, client=ua),
            ConfirmAuthorship(creator=user, client=ua, submitter_is_author=True),
            SetLicense(
                creator=user,
                client=ua,
                license_uri=cc0,
                license_name='CC0 1.0'
            ),
            ConfirmPolicy(creator=user, client=ua),
            SetPrimaryClassification(creator=user, client=ua,
                                     category='astro-ph.GA'),
            SetUploadPackage(
                creator=user, client=ua,
                checksum="a9s9k342900skks03330029k",
                source_format=SubmissionContent.Format.TEX,
                identifier="123",
                uncompressed_size=593992,
                compressed_size=59392,
            ),
            SetTitle(creator=user, client=ua, title='foo title'),
            SetAbstract(creator=user, client=ua, abstract='ab stract' * 20),
            SetComments(creator=user, client=ua, comments='indeed'),
            SetReportNumber(creator=user, client=ua, report_num='the number 12'),
            SetAuthors(
                creator=user, client=ua,
                authors=[Author(
                    order=0,
                    forename='Bob',
                    surname='Paulson',
                    email='Robert.Paulson@nowhere.edu',
                    affiliation='Fight Club'
                )]
            ),
            FinalizeSubmission(creator=user, client=ua)
        )

        # announced the submission
        with Session() as session:
            db_submission = session.query(classic.Submission).get(submission.submission_id)
            db_submission.status = 7  # published
            db_document = classic.Document(paper_id='1234.5678',
                                           title=submission.metadata.title,
                                           submitter_email=submission.creator.email,
                                           #submitter=submission.creator.user_id,
                                           )
            db_submission.doc_paper_id = '1234.5678'
            db_submission.document = db_document
            session.add(db_submission)
            session.add(db_document)
            session.commit()

    submission_id = submission.submission_id

    def _parse_csrf_token(response):
        return parse_csrf_token(response)


    """User requests withdrawal of a announced submission."""
    endpoint = f'/{submission_id}/withdraw'
    response = client.get(endpoint)
    assert response.status_code == status.OK
    assert response.content_type == 'text/html; charset=utf-8'
    assert b'Request withdrawal' in response.data
    token = _parse_csrf_token(response)

    # Set the withdrawal reason, but make it huge.
    request_data = {'withdrawal_reason': 'This is the reason' * 400,
                    'csrf_token': token}
    response = client.post(endpoint, data=request_data,
                                )
    assert response.status_code == status.OK
    token = _parse_csrf_token(response)

    # Set the withdrawal reason to something reasonable (ha).
    request_data = {'withdrawal_reason': 'This is the reason',
                    'csrf_token': token}
    response = client.post(endpoint, data=request_data,
                                )
    assert response.status_code == status.OK
    assert response.content_type == 'text/html; charset=utf-8'
    assert b'Confirm and Submit' in response.data
    token = _parse_csrf_token(response)

    # Confirm the withdrawal request.
    request_data['confirmed'] = True
    request_data['csrf_token'] = token
    response = client.post(endpoint, data=request_data,
                                )
    assert response.status_code == status.SEE_OTHER

    with app.app_context():
        with Session() as session:
            # What happened.
            db_submissions = session.query(classic.Submission) \
                .filter(classic.Submission.doc_paper_id == '1234.5678')
            assert db_submissions.count() == 2, "Creates a second row for the withdrawal"
            db_submission = db_submissions \
                .order_by(classic.Submission.submission_id.desc()) \
                .first()
            assert db_submission.type == 'wdr'
