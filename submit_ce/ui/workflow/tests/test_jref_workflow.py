"""Tests for the submission application as a whole."""
from http import HTTPStatus as status

from arxiv.db import models as classic
from arxiv.db import Session
from flask import current_app

from submit_ce.domain.agent import InternalClient
from submit_ce.domain.event import CreateSubmissionVersion
from submit_ce.ui.tests.csrf_util import parse_csrf_token


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


def test_create_jref_submission(app, authorized_client, published_submission):
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
            rows = session.query(classic.Submission) \
                          .filter(classic.Submission.doc_paper_id == paper_id) \
                          .all()
            assert len(rows) == 2, "Creates a second row for the JREF"

            # The original announced row and the new jref row.
            orig = next(r for r in rows if r.type != 'jref')
            jref = next(r for r in rows if r.type == 'jref')

            # Identity: it is a jref row for the same document/paper, same version.
            assert jref.type == 'jref'
            assert jref.doc_paper_id == paper_id
            assert jref.document_id is not None
            assert jref.document_id == orig.document_id, \
                "jref shares the announced paper's document"
            assert jref.version == orig.version, "jref does not bump the version"
            assert jref.submission_id != orig.submission_id, "jref is a distinct row"

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
    """A jref cannot be made against a submission that is not yet announced."""
    submission_id = sub_created.submission_id
    endpoint = f'/{submission_id}/jref'

    def jref_count():
        with app.app_context():
            with Session() as session:
                return session.query(classic.Submission) \
                              .filter(classic.Submission.type == 'jref') \
                              .count()

    before = jref_count()

    # GET is rejected: the submission has never been announced, so there is
    # nothing to add a journal reference to. The user is redirected away.
    response = authorized_client.get(endpoint)
    assert response.status_code == status.SEE_OTHER

    # POST is rejected the same way, and no jref row is created.
    response = authorized_client.post(
        endpoint,
        data={'doi': '10.1000/182',
              'journal_ref': 'foo journal 1992',
              'report_num': 'abc report 42',
              'confirmed': True})
    assert response.status_code == status.SEE_OTHER

    assert jref_count() == before, "No jref row for an unannounced submission"


def test_second_jref_absorbed_into_first(app, authorized_client,
                                         published_submission):
    """A second jref edit on a published paper updates the existing jref row
    rather than creating another one."""
    submission, paper_id = published_submission
    submission_id = submission.submission_id
    endpoint = f'/{submission_id}/jref'

    def submit_jref(doi, journal_ref, report_num):
        """Run the two-step confirm-and-submit jref flow."""
        response = authorized_client.get(endpoint)
        data = {'doi': doi, 'journal_ref': journal_ref,
                'report_num': report_num,
                'csrf_token': parse_csrf_token(response)}
        # First POST previews and asks for confirmation.
        response = authorized_client.post(endpoint, data=data)
        assert response.status_code == status.OK
        assert b'Confirm and Submit' in response.data
        # Second POST, confirmed, commits.
        data['confirmed'] = True
        data['csrf_token'] = parse_csrf_token(response)
        response = authorized_client.post(endpoint, data=data)
        assert response.status_code == status.SEE_OTHER

    # First jref submission.
    submit_jref('10.1000/182', 'foo journal 1992', 'abc report 42')
    # Second jref submission with different values.
    submit_jref('10.2000/999', 'bar journal 2001', 'xyz report 77')

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

    The guard lives in the jref events' ``validate_under_lock``, so it fires
    when the confirmed jref is saved. A friendly GET-time redirect is a later
    phase; for now the uncaught ``InvalidEvent`` surfaces as a 500. Either way
    no jref row is created and the replacement is left untouched."""
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

    # Run the two-step confirm-and-submit jref flow. The confirmed POST is
    # rejected under the row lock because a replacement is in progress.
    endpoint = f'/{submission_id}/jref'
    response = authorized_client.get(endpoint)
    assert response.status_code == status.OK
    data = {'doi': '10.1000/182', 'journal_ref': 'foo journal 1992',
            'report_num': 'abc report 42',
            'csrf_token': parse_csrf_token(response)}
    response = authorized_client.post(endpoint, data=data)
    assert response.status_code == status.OK
    data['confirmed'] = True
    data['csrf_token'] = parse_csrf_token(response)
    response = authorized_client.post(endpoint, data=data)
    assert response.status_code == status.INTERNAL_SERVER_ERROR

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
