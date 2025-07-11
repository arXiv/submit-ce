import os
import shutil
import tempfile
import uuid
from datetime import datetime, timedelta

import pytest
from zoneinfo import ZoneInfo
from arxiv.auth import domain, auth
from flask import testing, Flask
from werkzeug.datastructures import Headers

from arxiv.taxonomy.definitions import CATEGORIES

import submit_ce

from submit_ce.api.domain.agent import InternalClient
from submit_ce.api.domain.event import ConfirmAuthorship, ConfirmContactInformation, ConfirmPolicy, FinalizeSubmission, SetAbstract, SetAuthors, SetComments, SetLicense, SetPrimaryClassification, SetReportNumber, SetTitle, SetUploadPackage
from submit_ce.api.domain.submission import Author
from submit_ce.ui.tests import TestClientArxivAuth
from submit_ce.ui import backend

# to ensure we can import this due to confusing errors if it is missing.

# to ensure we can import this due to confusing errors if deps are missing.
#import submit_ce.api.implementations.legacy_implementation

from submit_ce.make_test_db import create_all_legacy_db, bootstrap_db


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
    engine, url, test_db_file = create_all_legacy_db(test_db_file)
    return engine, url, test_db_file


@pytest.fixture(scope='session')
def legacy_db_w_bootstrap(test_db_file, jwt_secret, classic_db_uri_envvar):
    jwt = bootstrap_db(db_uri=f"sqlite:///{test_db_file}", jwt_secret=jwt_secret)
    engine, url, test_db_file = create_all_legacy_db(test_db_file)
    return engine, url, test_db_file, jwt


@pytest.fixture(scope='session')
def legacy_db(legacy_db_w_bootstrap):
    engine, url, t_db_file, jwt = legacy_db_w_bootstrap
    return engine, url, t_db_file, jwt


@pytest.fixture
def app(legacy_db, jwt_secret) -> Flask:
    engine, uri, _, user_jwt = legacy_db

    from submit_ce.ui.config import settings as sce_settings
    sce_settings.JWT_SECRET = jwt_secret
    sce_settings.CLASSIC_DB_URI = uri

    from submit_ce.ui.factory import create_web_app
    app = create_web_app()
    app.config["CLASSIC_DB_URI"] = uri
    app.config["JWT_SECRET"] = jwt_secret
    return app


@pytest.fixture
def authorized_user_session(app, jwt_secret):
    with app.app_context():

        start = datetime.now(ZoneInfo("US/Eastern"))

        end = start + timedelta(seconds=36000)
        session = domain.Session(
            session_id='123-session-abc',
            start_time=start, end_time=end,
            user=domain.User(
                user_id='235678',
                email='foo@foo.com',
                username='foouser',
                name=domain.UserFullName(forename="Jane", surname="Bloggs", suffix="III"),
                profile=domain.UserProfile(
                    affiliation="FSU",
                    rank=3,
                    country="de",
                    default_category=CATEGORIES['astro-ph.GA'],
                    submission_groups=['grp_physics']
                )
            ),
            authorizations=domain.Authorizations(
                scopes=[auth.scopes.CREATE_SUBMISSION,
                        auth.scopes.EDIT_SUBMISSION,
                        auth.scopes.VIEW_SUBMISSION],
                endorsements=['astro-ph.GA',
                              'astro-ph.CO',] # endorsements don't work here, arxiv-base doesn't add them
            )
        )
        ng_jwt = auth.tokens.encode(session, jwt_secret)
        return session, ng_jwt


@pytest.fixture
def authorized_user(authorized_user_session):
    session, _ = authorized_user_session
    user = backend._get_user(session)
    user.endorsements = ['astro-ph.GA', 'astro-ph.CO']
    return user


@pytest.fixture
def authorized_client(app, authorized_user_session):
    """Authorized client with db and jwt setup. """
    _, jwt = authorized_user_session
    app.test_client_class = TestClientArxivAuth
    yield app.test_client(jwt=jwt)


#################### submissions in different stages ####################
@pytest.fixture(scope="function")
def sub_created(app, authorized_user):
    """A submitted submission that is just created."""
    with app.app_context():
        user = authorized_user
        ua = InternalClient(name=f"test_client_{__file__}")
        submission, _ = backend.api.save(CreateSubmission(creator=user, client=ua))
        return submission


@pytest.fixture(scope="function")
def sub_verified_user(app, authorized_user, sub_created):
    """A submisison with VerifyUser done."""
    with app.app_context():
        user = authorized_user
        ua = InternalClient(name=f"test_client_{__file__}")
        submission, _ = backend.api.save(ConfirmContactInformation(creator=user, client=ua),
                                         submission_id=sub_created.submission_id)
        return submission

@pytest.fixture(scope="function")
def sub_authorship(app, authorized_user, sub_verified_user):
    """A submission with verify and confirm authorship done."""
    with app.app_context():
        user = authorized_user
        ua = InternalClient(name=f"test_client_{__file__}")
        submission, _ = backend.api.save(
            ConfirmAuthorship(creator=user, client=ua, submitter_is_author=True),
            submission_id = sub_verified_user.submission_id)
        return submission


@pytest.fixture(scope="function")
def sub_license(app, authorized_user, sub_authorship):
    """A submission with license set."""
    with app.app_context():
        user = authorized_user
        ua = InternalClient(name=f"test_client_{__file__}")
        cc0 = "http://creativecommons.org/publicdomain/zero/1.0/"
        submission, _ = backend.api.save(
            SetLicense(creator=user, client=ua, license_uri=cc0, license_name="CC0 1.0"),
            submission_id=sub_authorship.submission_id)
        return submission


@pytest.fixture(scope="function")
def sub_policy(app, authorized_user, sub_license):
    """A submission with policy done."""
    with app.app_context():
        user = authorized_user
        ua = InternalClient(name=f"test_client_{__file__}")
        submission, _ = backend.api.save(
            ConfirmPolicy(creator=user, client=ua), submission_id=sub_license.submission_id)
        return submission


@pytest.fixture(scope="function")
def sub_primary(app, authorized_user, sub_policy):
    """A submission with primary set."""
    with app.app_context():
        user = authorized_user
        ua = InternalClient(name=f"test_client_{__file__}")
        submission, _ = backend.api.save(
            SetPrimaryClassification(creator=user, client=ua, category="astro-ph.GA"),
            submission_id=sub_policy.submission_id)
        return submission


@pytest.fixture(scope="function")
def sub_files(app, authorized_user, sub_primary):
    """A submission marked as with files uploaded. (but no real files)"""
    with app.app_context():
        user = authorized_user
        ua = InternalClient(name=f"test_client_{__file__}")
        submission, _ = backend.api.save(
            SetUploadPackage(creator=user, client=ua,
                checksum="a9s9k342900skks03330029k",
                source_format=SubmissionContent.Format.TEX,
                identifier="123",
                uncompressed_size=593992,
                compressed_size=59392,
            ), submission_id=sub_primary.submission_id)
        return submission


@pytest.fixture(scope="function")
def sub_processed(app, authorized_user, sub_files):
    """A submission metadata."""
    with app.app_context():
        user = authorized_user
        ua = InternalClient(name=f"test_client_{__file__}")
        submission, _ = backend.api.save(
            SetTitle(creator=user, client=ua, title="foo title, submitted submission"),
            SetAbstract(creator=user, client=ua, abstract="foo abstract {__file__}"),
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
            ),submission_id=sub_files.submission_id)


@pytest.fixture(scope="function")
def sub_finalized(app, authorized_user, sub_processed):
    """A submission that is finalized."""
    with app.app_context():
        user = authorized_user
        ua = InternalClient(name=f"test_client_{__file__}")
        submission, _ = backend.api.save(
            FinalizeSubmission(creator=user, client=ua),
            submission_id=sub_processed.submission_id)
        return submission
