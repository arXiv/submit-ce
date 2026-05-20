import os
import io
import shutil
import tempfile
import uuid
import logging
from unittest.mock import MagicMock

import arxiv.db.models as classic
import pytest
from arxiv.auth import domain
from arxiv.auth.auth.tokens import encode
from arxiv.auth.legacy.accounts import register
from arxiv.auth.legacy.authenticate import authenticate
from arxiv.auth.legacy.exceptions import AuthenticationFailed
from arxiv.auth.legacy.sessions import create
from arxiv.db import Session
from arxiv.taxonomy.definitions import CATEGORIES
from flask import Flask, current_app
from sqlalchemy import desc, select

import submit_ce
from submit_ce.domain.event.file import UploadFiles
from submit_ce.implementations.compile import MockCompileMimesisPdf
import submit_ce.ui.auth
from submit_ce.domain import Author
from submit_ce.domain.uploads import SourceFormat
from submit_ce.domain.agent import InternalClient
from submit_ce.domain.event import (
    AddSecondaryClassification,
    ConfirmAuthorship,
    ConfirmContactInformation,
    ConfirmPolicy,
    ConfirmSourceProcessed,
    CreateSubmission,
    FinalizeSubmission,
    SetAbstract,
    SetAuthors,
    SetComments,
    SetLicense,
    SetPrimaryClassification,
    SetReportNumber,
    SetSourceFormat,
    SetTitle,
)


from submit_ce.make_test_db import bootstrap_db, create_all_db
from submit_ce.ui.tests import ClientArxivAuth
from submit_ce.ui.config import settings as sce_settings
from submit_ce.ui.factory import create_web_app


# to ensure we can import this due to confusing errors if it is missing.
# to ensure we can import this due to confusing errors if deps are missing.
#import submit_ce.api.implementations.legacy_implementation


def pytest_configure(config):
    """Run before all tests"""
    logging.getLogger("faker.factory").setLevel(logging.ERROR)
    logging.getLogger("submit_ce.make_test_db").setLevel(logging.ERROR)


def mocked_compile_service(app: Flask) -> None:
    """Alter the `app.api` to have a `CompileService` that always returns success and a PDF"""
    api = app.api
    api.compiler = MockCompileMimesisPdf()


def mocked_file_store(app: Flask) -> None:
    """Alter `app.api` to use a MockFileStore that accepts uploads in tests."""
    from submit_ce.implementations import MockFileStore
    app.api.store = MockFileStore()


@pytest.fixture(scope='session')
def jwt_secret():
    secret = str(uuid.uuid4())
    os.environ['JWT_SECRET'] = secret
    return secret

@pytest.fixture(scope='session')
def test_db_file():
    db_path = tempfile.mkdtemp()
    yield db_path + "/legacy.db"
    shutil.rmtree(db_path)

@pytest.fixture(scope='session')
def classic_db_uri_envvar(test_db_file):
    classic_db_uri = f"sqlite:///{test_db_file}"
    os.environ['CLASSIC_DB_URI'] = classic_db_uri
    return classic_db_uri

@pytest.fixture(scope='session')
def legacy_db_no_bootstrap(test_db_file, classic_db_uri_envvar):
    engine, url, test_db_file = create_all_db(test_db_file)
    return engine, url, test_db_file


@pytest.fixture(scope='session')
def legacy_db_w_bootstrap(test_db_file, jwt_secret, classic_db_uri_envvar):
    jwt = bootstrap_db(db_uri=f"sqlite:///{test_db_file}", jwt_secret=jwt_secret)
    engine, url, test_db_file = create_all_db(test_db_file)
    return engine, url, test_db_file, jwt


@pytest.fixture(scope='session')
def legacy_db(legacy_db_w_bootstrap):
    engine, url, t_db_file, jwt = legacy_db_w_bootstrap
    return engine, url, t_db_file, jwt


@pytest.fixture
def app(legacy_db, jwt_secret):
    engine, uri, _, user_jwt = legacy_db

    sce_settings.JWT_SECRET = jwt_secret
    sce_settings.CLASSIC_DB_URI = uri
    sce_settings.STORE = "null"

    app = create_web_app()
    app.config["CLASSIC_DB_URI"] = uri
    app.config["JWT_SECRET"] = jwt_secret

    yield app


@pytest.fixture
def authorized_user_session(app, jwt_secret, mocker):
    with app.app_context():
        username="foouser"
        email="foo@foo.com"
        user_id = '235678'
        pw = "fakepw-"+jwt_secret
        user, auths = None, None
        try:
            user, auths = authenticate(email, pw)
        except AuthenticationFailed:
            pass

        if not user:
            user = domain.User(
                    user_id=user_id,
                    email=email,
                    username=username,
                    name=domain.UserFullName(forename="Jane", surname="Bloggs", suffix="III"),
                    profile=domain.UserProfile(
                        affiliation="FSU",
                        rank=3,
                        country="de",
                        default_category=CATEGORIES['astro-ph.GA'],
                        submission_groups=['grp_physics']
                    )
            )
            user, auths = register(user, pw, "127.0.0.1", "localhost")
            Session.add(classic.Endorsement(endorsee_id=user.user_id,
                                            archive="astro-ph", subject_class="GA",
                                            flag_valid=1, type="auto", point_value=10,
                                            issued_when=11074371513))
            Session.add(classic.Endorsement(endorsee_id=user.user_id,
                                            archive="astro-ph", subject_class="CO",
                                            flag_valid=1, type="auto", point_value=10,
                                            issued_when=11074371513))
            Session.commit()

        session = create(auths, "127.0.0.1", "localhost", "", user)
        ng_jwt = encode(session, jwt_secret)

        return session, ng_jwt


@pytest.fixture
def authorized_user(authorized_user_session, mocker):
    session, _ = authorized_user_session
    user, _ = submit_ce.ui.auth.user_and_client_from_session(session)
    return user


@pytest.fixture
def authorized_client(app, authorized_user_session):
    """Authorized client with db and jwt setup. """
    _, jwt = authorized_user_session
    app.test_client_class = ClientArxivAuth
    yield app.test_client(jwt=jwt)


#################### submissions in different stages ####################
@pytest.fixture(scope="function")
def sub_created(app, authorized_user):
    """A submitted submission that is just created."""
    with app.app_context():
        user = authorized_user
        ua = InternalClient(name=f"test_client_{__file__}")
        submission, _ = current_app.api.save(CreateSubmission(creator=user, client=ua))
        return submission


@pytest.fixture(scope="function")
def sub_verified_user(app, authorized_user, sub_created):
    """A submisison with VerifyUser done."""
    with app.app_context():
        user = authorized_user
        ua = InternalClient(name=f"test_client_{__file__}")
        submission, _ = current_app.api.save(ConfirmContactInformation(creator=user, client=ua),
                                         submission_id=sub_created.submission_id)
        return submission

@pytest.fixture(scope="function")
def sub_authorship(app, authorized_user, sub_verified_user):
    """A submission with verify and confirm authorship done."""
    with app.app_context():
        user = authorized_user
        ua = InternalClient(name=f"test_client_{__file__}")
        submission, _ = current_app.api.save(
            ConfirmAuthorship(creator=user, client=ua, submitter_is_author=True),
            submission_id = sub_verified_user.submission_id)
        return submission


@pytest.fixture(scope="function")
def sub_policy(app, authorized_user, sub_authorship):
    """A submission with policy done."""
    with app.app_context():
        user = authorized_user
        ua = InternalClient(name=f"test_client_{__file__}")
        submission, _ = current_app.api.save(
            ConfirmPolicy(creator=user, client=ua, agreement_id=1),
            submission_id=sub_authorship.submission_id)
        return submission


@pytest.fixture(scope="function")
def sub_license(app, authorized_user, sub_policy):
    """A submission with license set."""
    with app.app_context():
        user = authorized_user
        ua = InternalClient(name=f"test_client_{__file__}")
        cc0 = "http://creativecommons.org/publicdomain/zero/1.0/"
        submission, _ = current_app.api.save(
            SetLicense(creator=user, client=ua, license_uri=cc0, license_name="CC0 1.0"),
            submission_id=sub_policy.submission_id)
        return submission


@pytest.fixture(scope="function")
def sub_primary(app, authorized_user, sub_license):
    """A submission with primary set."""
    with app.app_context():
        user = authorized_user
        ua = InternalClient(name=f"test_client_{__file__}")
        submission, _ = current_app.api.save(
            SetPrimaryClassification(creator=user, client=ua, category="astro-ph.GA"),
            submission_id=sub_license.submission_id)
        return submission


@pytest.fixture(scope="function")
def sub_cross(app, authorized_user, sub_primary):
    """A submission with cross set."""
    with app.app_context():
        user = authorized_user
        ua = InternalClient(name=f"test_client_{__file__}")
        submission, _ = current_app.api.save(
            AddSecondaryClassification(creator=user, client=ua, category="astro-ph.CO"),
            submission_id=sub_primary.submission_id)
        return submission


@pytest.fixture(scope="function")
def sub_files(app, authorized_user, sub_cross, mocker):
    """A submission marked as with files uploaded and a PDF file."""
    with app.app_context():
        user = authorized_user
        ua = InternalClient(name=f"test_client_{__file__}")
        class _FakePdf:
            filename = "paper.pdf"
            content_type = "application/pdf"
            stream = io.BytesIO(b"%PDF-1.4\n%%EOF\n")

        fake_stat = MagicMock()
        fake_stat.bytes = 10_000

        mock_store = MagicMock()
        mock_store.store_source_file.return_value = fake_stat

        original_store = current_app.api.store
        current_app.api.store = mock_store
        try:
            submission, _ = current_app.api.save(
                UploadFiles(creator=user, client=ua, files=[_FakePdf()]),
                submission_id=sub_cross.submission_id,
            )
        finally:
            current_app.api.store = original_store

        return submission


@pytest.fixture(scope="function")
def sub_reviewfiles(app, authorized_user, sub_files):
    # TODO what needs to be done here to make a submission that has the review files stage done?
    return sub_files


@pytest.fixture(scope="function")
def sub_processed(app, authorized_user, sub_reviewfiles):
    with app.app_context():
        user = authorized_user
        ua = InternalClient(name=f"test_client_{__file__}")
        submission, _ = current_app.api.save(
            SetSourceFormat(creator=user, client=ua, source_format=SourceFormat.TEX.value),
            ConfirmSourceProcessed(
                creator=user, client=ua,
                soruce_id="123",
                source_checksum="a9s9k342900skks03330029k",
                prefiew_checksum="pxxx",
                size_bytes=23432,
            )
            ,submission_id=sub_reviewfiles.submission_id)
        return submission



@pytest.fixture(scope="function")
def sub_metadata(app, authorized_user, sub_processed):
    """A submission metadata."""
    with app.app_context():
        user = authorized_user
        ua = InternalClient(name=f"test_client_{__file__}")
        submission, _ = current_app.api.save(
            SetTitle(creator=user, client=ua, title="Foo title, submitted submission"),
            SetAbstract(creator=user, client=ua, abstract="Foo abstract {__file__}"),
            SetComments(creator=user, client=ua, comments="pickels"),
            SetReportNumber(creator=user, client=ua, report_num="the number 13"),
            SetAuthors(creator=user, client=ua,
                authors=[
                    Author(
                        order=0,
                        forename="Bob",
                        surname="Paulson",
                        email="Robert.Paulson@nowhere.edu",
                        affiliation="Fight Club",
                    )
                ],
            ),submission_id=sub_processed.submission_id)
        return submission


@pytest.fixture(scope="function")
def sub_finalized(app, authorized_user, sub_metadata):
    """A submission that is finalized."""
    assert sub_metadata
    with app.app_context():
        user = authorized_user
        ua = InternalClient(name=f"test_client_{__file__}")
        submission, _ = current_app.api.save(
            FinalizeSubmission(creator=user, client=ua),
            submission_id=sub_metadata.submission_id)
        return submission




@pytest.fixture(scope="function")
def submitted_submission(app, authorized_user):
    """A submitted submission."""
    with app.app_context():
        user = authorized_user
        ua = InternalClient(name=f"test_client_{__file__}")
        # Create a finalized submission.
        ua = InternalClient(name=f"test_client_{__file__}")
        cc0 = "http://creativecommons.org/publicdomain/zero/1.0/"
        submission, _ = current_app.api.save(
            CreateSubmission(creator=user, client=ua),
            ConfirmContactInformation(creator=user, client=ua),
            ConfirmAuthorship(creator=user, client=ua, submitter_is_author=True),
            SetLicense(creator=user, client=ua, license_uri=cc0, license_name="CC0 1.0"),
            ConfirmPolicy(creator=user, client=ua, agreement_id=1),
            SetPrimaryClassification(creator=user, client=ua, category="astro-ph.GA"),
            UploadFiles(creator=user, client=ua,
                checksum="a9s9k342900skks03330029k",
                source_format=SourceFormat.TEX,
                identifier="123",
                uncompressed_size=593992,
                compressed_size=59392,
            ),
            SetSourceFormat(creator=user, client=ua, source_format=SourceFormat.TEX.value),
            SetTitle(creator=user, client=ua, title="Foo title, submitted submission"),
            SetAbstract(creator=user, client=ua, abstract="Foo abstract {__file__} and the reasons for why the place feels like original equipment."),
            SetComments(creator=user, client=ua, comments="pickels"),
            SetReportNumber(creator=user, client=ua, report_num="CERN-PH-EP/2999-018"),
            SetAuthors(creator=user, client=ua,
                authors=[
                    Author(
                        order=0,
                        forename="Bob",
                        surname="Paulson",
                        email="Robert.Paulson@nowhere.edu",
                        affiliation="Fight Club",
                    )
                ],
            ),
            FinalizeSubmission(creator=user, client=ua),
        )
        return submission


@pytest.fixture(scope="function")
def published_submission(app, authorized_user):
    """A published submission."""
    with app.app_context():
        user = authorized_user
        ua = InternalClient(name=f"test_client_{__file__}")
        # Create a finalized submission.
        ua = InternalClient(name=f"test_client_{__file__}")
        cc0 = "http://creativecommons.org/publicdomain/zero/1.0/"
        submission, _ = current_app.api.save(
            CreateSubmission(creator=user, client=ua),
            ConfirmContactInformation(creator=user, client=ua),
            ConfirmAuthorship(creator=user, client=ua, submitter_is_author=True),
            SetLicense(
                creator=user, client=ua, license_uri=cc0, license_name="CC0 1.0"
            ),
            ConfirmPolicy(creator=user, client=ua, agreement_id=1),
            SetPrimaryClassification(creator=user, client=ua, category="astro-ph.GA"),
            UploadFiles(
                creator=user,
                client=ua,
                checksum="a9s9k342900skks03330029k",
                source_format=SourceFormat.TEX,
                identifier="123",
                uncompressed_size=593992,
                compressed_size=59392,
            ),
            SetSourceFormat(creator=user, client=ua, source_format=SourceFormat.TEX.value),
            SetTitle(creator=user, client=ua, title="Foo bar and the right data"),
            SetAbstract(creator=user, client=ua, abstract="The correct foo bar and the right data is exactly what is needed for this test." * 20),
            SetComments(creator=user, client=ua, comments="indeed"),
            SetReportNumber(creator=user, client=ua, report_num="CERN-PH-EP/2999-018"),
            SetAuthors(
                creator=user,
                client=ua,
                authors=[
                    Author(
                        order=0,
                        forename="Bob",
                        surname="Paulson",
                        email="Robert.Paulson@nowhere.edu",
                        affiliation="Fight Club",
                    )
                ],
            ),
            FinalizeSubmission(creator=user, client=ua),
        )

        # announced the submission
        with Session() as session:
            maxid=session.execute(select(classic.Document.paper_id)
                                .order_by(desc(classic.Document.paper_id))
                                .limit(1)).first()
            if maxid and maxid[0]:
                yymm, monthid = maxid[0].split(".")
                paper_id = f"{yymm}.{int(monthid)+1}"
            else:
                paper_id = "1234.56789"

            db_submission = session.query(classic.Submission).get(submission.submission_id)
            if not db_submission:
                raise RuntimeError(f"No db row for {submission.submission_id}")
            db_submission.status = 7  # published
            db_submission.paper_id = paper_id
            db_document = classic.Document(
                paper_id=paper_id,
                title=submission.metadata.title,
                submitter_email=submission.creator.email,
                # submitter=submission.creator.user_id,
            )
            db_submission.doc_paper_id = paper_id
            db_submission.document = db_document
            session.add(db_submission)
            session.add(db_document)
            session.commit()
            return current_app.api.get(str(submission.submission_id)), paper_id
