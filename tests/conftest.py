import shutil
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# to ensure we can import this due to confusing errors if it is missing.
import arxiv.db

# to ensure we can import this due to confusing errors if deps are missing.
import submit_ce.fastapi.implementations.legacy_implementation

from submit_ce.fastapi.config import DEV_SQLITE_FILE
from .make_test_db import create_all_legacy_db



@pytest.fixture(scope='session')
def test_db_file():
    db_path = tempfile.mkdtemp()
    yield db_path + "/" + DEV_SQLITE_FILE
    shutil.rmtree(db_path)


@pytest.fixture(scope='session')
def legacy_db(test_db_file):
    return create_all_legacy_db(test_db_file)


@pytest.fixture
def app(legacy_db) -> FastAPI:
    engine, url, test_db_file = legacy_db
    from arxiv.config import settings
    settings.CLASSIC_DB_URI = url

    # Don't import until now so settings can be altered
    from submit_ce.fastapi.app import app as application
    application.dependency_overrides = {}
    return application


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)

