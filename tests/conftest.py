import shutil
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session



@pytest.fixture(scope='session')
def test_dir():
    db_path = tempfile.mkdtemp()
    yield db_path
    shutil.rmtree(db_path)

@pytest.fixture(scope='session')
def classic_db(test_dir, echo: bool=False) -> None:
    """Temp classic db with all tables created but no data."""
    url = f"sqlite:///{test_dir}/test_classic.db"
    engine = create_engine(url, echo=echo)
    from arxiv.db.models import configure_db_engine
    configure_db_engine(engine, None)
    from arxiv.db import metadata
    with Session(engine) as session:
        import arxiv.db.models as models
        models.configure_db_engine(session.get_bind(), None)
        metadata.create_all(bind=engine)
        session.commit()

    yield (engine, url, test_dir)

@pytest.fixture
def app(test_dir, classic_db) -> FastAPI:
    engine, url, test_dir = classic_db
    from arxiv.config import settings
    settings.CLASSIC_DB_URI = url

    # Don't import until now so settings can be altered
    from submit_ce.submit_fastapi import app as application
    application.dependency_overrides = {}

    return application


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)
