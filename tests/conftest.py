import shutil
import tempfile
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# to ensure we can import this due to confusing errors if it is missing.
import arxiv.db

# to ensure we can import this due to confusing errors if deps are missing.
import submit_ce.api.implementations.legacy_implementation

from submit_ce.api.config import DEV_SQLITE_FILE
from .make_test_db import create_all_legacy_db, bootstrap_db


@pytest.fixture(scope="session")
def jwt_secret():
    return str(uuid.uuid4())

@pytest.fixture(scope='session')
def test_db_file():
    db_path = tempfile.mkdtemp()
    yield db_path + "/" + DEV_SQLITE_FILE
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
def app(legacy_db, jwt_secret) -> FastAPI:
    engine, url, _, user_jwt = legacy_db
    from arxiv.config import settings
    settings.CLASSIC_DB_URI = url

    from submit_ce.api.config import config
    config.jwt_secret = jwt_secret

    # Don't import until now so settings can be altered
    from submit_ce.api.app import app as application
    application.dependency_overrides = {}
    return application


@pytest.fixture
def client(app, legacy_db) -> TestClient:
    """Authorized client with user jwt setup """
    _, _, _, user_jwt = legacy_db
    return TestClient(app,
                      headers= {"Authorization": f"Bearer {user_jwt}",})


