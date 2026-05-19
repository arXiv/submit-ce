"""Tests for the submission application as a whole."""
import pytest
from http import HTTPStatus as status

from arxiv.db import models as classic


from submit_ce.ui.tests.csrf_util import parse_csrf_token

from arxiv.db import Session


# @pytest.fixture
# def jref_user_and_token(app):
#     with app.app_context():
#         user = PublicUser('1234', 'foo@bar.com', endorsements=['astro-ph.GA'])
#         token = generate_token('1234', 'foo@bar.com', 'foouser',
#                                 scope=[scopes.CREATE_SUBMISSION,
#                                        scopes.EDIT_SUBMISSION,
#                                        scopes.VIEW_SUBMISSION,
#                                        scopes.READ_UPLOAD,
#                                        scopes.WRITE_UPLOAD,
#                                        scopes.DELETE_UPLOAD_FILE],
#                                 endorsements=['astro-ph.GA','astro-ph.CO'])
#         return user, token


# @pytest.fixture
# def jref_auth_client(app, jref_user_and_token):
#     user, jwt = jref_user_and_token
#     with app.app_context():
#         app.test_client_class = TestClientArxivAuth
#         yield app.test_client(jwt=jwt)


# class TestJREFWorkflow(CtrlBase):
#     """Tests that progress through the JREF workflow."""

#     @pytest.fixture(autouse=True)
#     def fixture_1(self, jref_user_and_token, jref_auth_client):
#         self.user = jref_user_and_token[0]
#         self.jwt = jref_user_and_token[1]
#         self.jref_auth_client = jref_auth_client
#         self.api_client = Client(native_id=f"totally_fake_cliet_native_id_{__file__}",
#                                  remote_addr="127.0.0.1")

    # def setUp(self):
    #     """Create an application instance."""

        # os.environ['JWT_SECRET'] = str(self.app.config.get('JWT_SECRET', 'fo'))
        # _, self.db = tempfile.mkstemp(suffix='.db')
        # self.app.config['CLASSIC_DATABASE_URI'] = f'sqlite:///{self.db}'
        # self.user = PublicUser('1234', 'foo@bar.com', endorsements=['astro-ph.GA'])
        # self.token = generate_token('1234', 'foo@bar.com', 'foouser',
        #                             scope=[scopes.CREATE_SUBMISSION,
        #                                    scopes.EDIT_SUBMISSION,
        #                                    scopes.VIEW_SUBMISSION,
        #                                    scopes.READ_UPLOAD,
        #                                    scopes.WRITE_UPLOAD,
        #                                    scopes.DELETE_UPLOAD_FILE],
        #                             endorsements=['astro-ph.GA','astro-ph.CO'])
        # self.headers = {'Authorization': self.token}
        # self.client = self.app.test_client()

    # Create and announce a submission.
    # with self.app.app_context():
    #     cc0 = 'http://creativecommons.org/publicdomain/zero/1.0/'
    #     self.submission, _ = current_app.api.save(
    #         CreateSubmission(creator=self.user, client=self.api_client),
    #         ConfirmContactInformation(creator=self.user),
    #         ConfirmAuthorship(creator=self.user, submitter_is_author=True),
    #         SetLicense(
    #             creator=self.user,
    #             license_uri=cc0,
    #             license_name='CC0 1.0'
    #         ),
    #         ConfirmPolicy(creator=self.user),
    #         SetPrimaryClassification(creator=self.user,
    #                                  category='astro-ph.GA'),
    #         SetUploadPackage(
    #             creator=self.user,
    #             checksum="a9s9k342900skks03330029k",
    #             source_format=SubmissionContent.Format.TEX,
    #             identifier='123',
    #             uncompressed_size=593992,
    #             compressed_size=59392,
    #         ),
    #         SetTitle(creator=self.user, title='foo title'),
    #         SetAbstract(creator=self.user, abstract='ab stract' * 20),
    #         SetComments(creator=self.user, comments='indeed'),
    #         SetReportNumber(creator=self.user, report_num='the number 12'),
    #         SetAuthors(
    #             creator=self.user,
    #             authors=[Author(
    #                 order=0,
    #                 forename='Bob',
    #                 surname='Paulson',
    #                 email='Robert.Paulson@nowhere.edu',
    #                 affiliation='Fight Club'
    #             )]
    #         ),
    #         FinalizeSubmission(creator=self.user)
    #     )

    #     # announced the submission, so we can add a jref to it
    #     with Session() as session:
    #         db_submission = session.query(models.Submission).get(self.submission.submission_id)
    #         db_submission.status = models.Submission.ANNOUNCED
    #         db_document = models.Document(paper_id='1234.5678')
    #         db_submission.doc_paper_id = '1234.5678'
    #         db_submission.document = db_document
    #         session.add(db_submission)
    #         session.add(db_document)
    #         session.commit()

    # self.submission_id = self.submission.submission_id


def test_create_submission(app, authorized_client, published_submission):
    """Test user creates a jref submission via web UI."""
    submission, paper_id = published_submission
    submission_id = submission.submission_id

    # Get the JREF page.
    endpoint = f'/{submission_id}/jref'
    response = authorized_client.get(endpoint)
    assert response.status_code == status.OK and response.content_type == 'text/html; charset=utf-8'
    assert b'Journal reference' in response.data
    token = parse_csrf_token(response)

    # Set the DOI, journal reference, report number.
    request_data = {'doi': '10.1000/182',
                    'journal_ref': 'foo journal 1992',
                    'report_num': 'abc report 42',
                    'csrf_token': token}
    response = authorized_client.post(endpoint, data=request_data)
    assert response.status_code == status.OK and  response.content_type == 'text/html; charset=utf-8'
    assert b'Confirm and Submit' in response.data
    token = parse_csrf_token(response)

    request_data['confirmed'] = True
    request_data['csrf_token'] = token
    response = authorized_client.post(endpoint, data=request_data)
    assert response.status_code == status.SEE_OTHER

    with app.app_context():
        with Session() as session:
            db_submission = session.query(classic.Submission) \
                                   .filter(classic.Submission.doc_paper_id == paper_id)
            assert db_submission.count() == 2, "Creates a second row for the JREF"
