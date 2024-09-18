import shutil
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from make_test_db import legacy_db



@pytest.fixture
def app(legacy_db) -> FastAPI:
    engine, url, test_db_file = legacy_db
    from arxiv.config import settings
    settings.CLASSIC_DB_URI = url

    # Don't import until now so settings can be altered
    from submit_ce.submit_fastapi.app import app as application
    application.dependency_overrides = {}
    return application


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)
