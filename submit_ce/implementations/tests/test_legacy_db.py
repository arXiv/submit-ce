import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import MagicMock, patch

from submit_ce.implementations.legacy_implementation.models import Base, License, Submission, DBEvent
from sqlalchemy.exc import OperationalError
from submit_ce.implementations.legacy_implementation.db import (
    get_licenses,
    get_events,
    get_submission,
    handle_operational_errors,
)
from submit_ce.domain.exceptions import NoSuchSubmission

@pytest.fixture
def db_session():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

def test_get_licenses(db_session):
    # Setup test data
    lic1 = License(name="http://license1", label="License 1", active="1", sequence=1)
    lic2 = License(name="http://license2", label="License 2", active="0", sequence=2)
    db_session.add(lic1)
    db_session.add(lic2)
    db_session.commit()

    licenses = get_licenses(db_session)
    
    assert len(licenses) == 1
    assert licenses[0].uri == "http://license1"
    assert licenses[0].name == "License 1"

def test_get_events_no_submission(db_session):
    with pytest.raises(NoSuchSubmission, match="Submission 999 not found"):
        get_events(db_session, 999)

def test_get_submission_not_found(db_session):
    with pytest.raises(NoSuchSubmission, match="Submission 999 not found"):
        get_submission(db_session, 999)

def test_get_submission_found_but_not_create_submission(db_session):
    sub = Submission(
        submission_id=123,
        type=Submission.NEW_SUBMISSION,
        status=Submission.WORKING,
        created=datetime.now(),
        updated=datetime.now()
    )
    db_session.add(sub)
    
    event = DBEvent(
        event_id="evt123",
        event_type="SomethingElse",
        submission_id=123,
        created=datetime.now(),
        data=b'{}'
    )
    db_session.add(event)
    db_session.commit()

    # The db.py code requires this setup for a classic submission
    # it uses load() under the hood
    # If not all requirements of load() are met, it returns None and raises NoSuchSubmission or an error.
    # We mock out `get_events` and `load` to just test the flow for get_submission.
    with patch('submit_ce.implementations.legacy_implementation.db.load') as mock_load, \
         patch('submit_ce.implementations.legacy_implementation.db.get_events') as mock_get_events:
        mock_load.return_value = MagicMock()
        mock_get_events.return_value = [MagicMock()] # Return some mock event that is not CreateSubmission
        
        submission, events = get_submission(db_session, 123)
        assert submission is not None
        assert events == []
        mock_load.assert_called()

def test_handle_operational_errors():
    @handle_operational_errors
    def failing_func():
        raise OperationalError("stmt", "params", Exception("orig"))

    with pytest.raises(OperationalError, match="Classic database unavailable"):
        failing_func()
