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
# to ensure we can import this due to confusing errors if it is missing.

# to ensure we can import this due to confusing errors if deps are missing.
#import submit_ce.api.implementations.legacy_implementation

from submit_ce.make_test_db import create_all_legacy_db, bootstrap_db


@pytest.fixture(scope="session")
def jwt_secret():
    return str(uuid.uuid4())

@pytest.fixture(scope='session')
def test_db_file():
    db_path = tempfile.mkdtemp()
    yield db_path + "/legacy.db"
    shutil.rmtree(db_path)


@pytest.fixture(scope='session')
def legacy_db_no_bootstrap(test_db_file):
    engine, url, test_db_file = create_all_legacy_db(test_db_file)
    return engine, url, test_db_file

@pytest.fixture(scope='session')
def legacy_db_w_bootstrap(test_db_file, jwt_secret):
    jwt = bootstrap_db(db_uri=f"sqlite:///{test_db_file}", jwt_secret=jwt_secret)
    engine, url, test_db_file = create_all_legacy_db(test_db_file)
    return engine, url, test_db_file, jwt

@pytest.fixture(scope='session')
def legacy_db(
        legacy_db_w_bootstrap
    #legacy_db_no_bootstrap
):
    #engine, url, test_db_file, None = legacy_db_no_bootstrap
    engine, url, test_db_file, jwt = legacy_db_w_bootstrap
    return engine, url, test_db_file, jwt


@pytest.fixture
def app(legacy_db, jwt_secret) -> Flask:
    engine, url, _, user_jwt = legacy_db
    from arxiv.config import settings
    settings.CLASSIC_DB_URI = url
    #settings.JWT_SECRET = jwt_secret

    # Don't import until now so settings can be altered
    from submit_ce.ui.factory import create_web_app
    return create_web_app()


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
                endorsements=[CATEGORIES['astro-ph.CO'],
                              CATEGORIES['astro-ph.GA']]
            )
        )
        ng_jwt = auth.tokens.encode(session, jwt_secret)
        return session, ng_jwt



@pytest.fixture
def authorized_client(app, authorized_user_session):
    """Authorized client with db and jwt setup. """

    session, ng_jwt = authorized_user_session
    class TestClientArxivAuth(testing.FlaskClient):
        def open(self, *args, **kwargs):
            api_key_headers = Headers({
                'Authorized': ng_jwt
            })
            headers = kwargs.pop('headers', Headers())
            headers.extend(api_key_headers)
            kwargs['headers'] = headers
            return super().open(*args, **kwargs)

    with app.app_context():
        app.test_client_class = TestClientArxivAuth
        yield app.test_client()
