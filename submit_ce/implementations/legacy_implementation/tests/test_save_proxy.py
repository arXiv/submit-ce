"""Tests for proxy-submitter persistence in the legacy DB implementation.

The legacy ``arXiv_submissions`` row stores proxy information in a single
``proxy`` column (``VARCHAR(255)``). The submitter contact name and email
shown to the world are kept in ``submitter_name`` and ``submitter_email``
on the same row, even when the submission is being made on behalf of someone
else. ``proxy`` is just a flag/identifier indicating the row was proxied.

These tests verify the two halves of the round-trip:

* ``Submission.update_from_submission`` writes ``submission.proxy`` to the
  ``proxy`` column.
* ``db.to_submission`` reads the ``proxy`` column back into the domain
  ``Submission`` (or ``None`` when the column is empty/null).
"""
from datetime import datetime, timezone
from typing import Optional

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from submit_ce.domain import Submission as DomainSubmission
from submit_ce.domain.agent import HttpClient, PublicUser
from submit_ce.domain.event import SetProxyInformation
from submit_ce.implementations.legacy_implementation import models
from submit_ce.implementations.legacy_implementation.db import to_submission


@pytest.fixture
def db_session():
    """An empty in-memory SQLite session with the legacy schema loaded."""
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _make_domain_submission(
    *,
    proxy: Optional[str],
    creator_name: str = "David Submitter",
    creator_email: str = "david@example.org",
) -> DomainSubmission:
    """Build a minimal domain Submission suitable for ``update_from_submission``."""
    submitter = PublicUser(
        user_id="123",
        name=creator_name,
        email=creator_email,
    )
    client = HttpClient(remote_addr="127.0.0.1", remote_host="localhost")
    return DomainSubmission(
        creator=submitter,
        owner=submitter,
        client=client,
        proxy=proxy,
        created=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _new_db_row() -> models.Submission:
    """Build a fresh ``models.Submission`` row of type ``new``, version 1."""
    return models.Submission(
        type=models.Submission.NEW_SUBMISSION,
        version=1,
    )


# ---------------------------------------------------------------------------
# update_from_submission writes proxy
# ---------------------------------------------------------------------------

def test_update_from_submission_writes_proxy_string():
    """A non-empty ``submission.proxy`` is copied to the row's ``proxy`` column."""
    submission = _make_domain_submission(proxy="David Submitter")
    dbs = _new_db_row()

    dbs.update_from_submission(submission)

    assert dbs.proxy == "David Submitter"


def test_update_from_submission_writes_none_when_not_proxied():
    """A ``None`` proxy is written through; the row's proxy stays ``None``."""
    submission = _make_domain_submission(proxy=None)
    dbs = _new_db_row()

    dbs.update_from_submission(submission)

    assert dbs.proxy is None


def test_update_from_submission_clears_existing_proxy():
    """Setting ``submission.proxy=None`` overwrites a previously-stored value.

    This guards against stale proxy markers when a submission's proxy state
    is removed.
    """
    submission = _make_domain_submission(proxy=None)
    dbs = _new_db_row()
    dbs.proxy = "stale value from earlier event"

    dbs.update_from_submission(submission)

    assert dbs.proxy is None


def test_update_from_submission_persists_proxy_to_db(db_session):
    """The proxy column survives a real session.commit / reload cycle."""
    submission = _make_domain_submission(proxy="David Submitter")
    dbs = _new_db_row()
    dbs.update_from_submission(submission)
    db_session.add(dbs)
    db_session.commit()
    submission_id = dbs.submission_id

    db_session.expire_all()
    reloaded = db_session.get(models.Submission, submission_id)

    assert reloaded.proxy == "David Submitter"
    # Submitter contact fields take their values from the (proxied) creator.
    assert reloaded.submitter_name == "David Submitter"
    assert reloaded.submitter_email == "david@example.org"


# ---------------------------------------------------------------------------
# to_submission reads proxy back
# ---------------------------------------------------------------------------

def _row_for_to_submission(*, proxy: Optional[str]) -> models.Submission:
    """Build a ``models.Submission`` row populated enough for ``to_submission``."""
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return models.Submission(
        submission_id=42,
        type=models.Submission.NEW_SUBMISSION,
        status=models.Submission.WORKING,
        version=1,
        submitter_id=123,
        submitter_name="David Submitter",
        submitter_email="david@example.org",
        remote_addr="127.0.0.1",
        remote_host="localhost",
        created=now,
        updated=now,
        proxy=proxy,
    )


def test_to_submission_reads_proxy_string():
    """A populated proxy column becomes ``submission.proxy`` (str)."""
    row = _row_for_to_submission(proxy="David Submitter")

    submission = to_submission(row)

    assert isinstance(submission.proxy, str)
    assert submission.proxy == "David Submitter"


def test_to_submission_reads_none_when_row_proxy_is_null():
    """When the proxy column is ``None``, ``submission.proxy`` is ``None``."""
    row = _row_for_to_submission(proxy=None)

    submission = to_submission(row)

    assert submission.proxy is None


def test_to_submission_treats_empty_string_proxy_as_none():
    """An empty string in the column is falsy and maps to ``None``.

    The conversion is ``str(row.proxy) if row.proxy else None`` — empty
    strings are treated as "not proxied". This prevents an empty-string
    column value from being interpreted as a (degenerate) proxy.
    """
    row = _row_for_to_submission(proxy="")

    submission = to_submission(row)

    assert submission.proxy is None


# ---------------------------------------------------------------------------
# Round-trip: write then read
# ---------------------------------------------------------------------------

def test_proxy_round_trip_through_db(db_session):
    """A proxied domain Submission survives a write-then-read cycle."""
    original = _make_domain_submission(proxy="David Submitter")

    dbs = _new_db_row()
    dbs.update_from_submission(original)
    db_session.add(dbs)
    db_session.commit()

    db_session.expire_all()
    reloaded_row = db_session.get(models.Submission, dbs.submission_id)
    rebuilt = to_submission(reloaded_row)

    assert rebuilt.proxy == "David Submitter"
    # Contact name/email come back from submitter_name / submitter_email,
    # which were populated from the (proxied) creator on save.
    assert rebuilt.creator.name == "David Submitter"
    assert rebuilt.creator.email == "david@example.org"


def test_non_proxy_round_trip_through_db(db_session):
    """A non-proxied submission round-trips with ``proxy is None``."""
    original = _make_domain_submission(proxy=None)

    dbs = _new_db_row()
    dbs.update_from_submission(original)
    db_session.add(dbs)
    db_session.commit()

    db_session.expire_all()
    reloaded_row = db_session.get(models.Submission, dbs.submission_id)
    rebuilt = to_submission(reloaded_row)

    assert rebuilt.proxy is None


# ---------------------------------------------------------------------------
# Full pipeline: SetProxyInformation event -> DB -> reload -> domain
# ---------------------------------------------------------------------------

def test_full_pipeline_event_through_db_to_domain(db_session):
    """Exercise the production flow end-to-end.

    1. Build a domain ``Submission`` for an authenticated proxy submitter.
    2. Apply a ``SetProxyInformation`` event (overwrites creator contact,
       sets ``submission.proxy``).
    3. Persist via ``update_from_submission`` + commit.
    4. Reload the row and rebuild the domain object via ``to_submission``.
    5. Assert the rebuilt submission carries the proxied contact and the
       proxy marker.

    This is the same sequence the ``verify_user`` controller drives in
    ``submit_ce/ui/controllers/new/verify_user.py`` when a submitter enters
    a proxy contact for the first time.
    """
    # 1. Domain Submission owned by the proxy submitter.
    proxy_submitter = PublicUser(
        user_id="123",
        name="David Submitter",
        email="david@example.org",
    )
    client = HttpClient(remote_addr="127.0.0.1", remote_host="localhost")
    submission = DomainSubmission(
        creator=proxy_submitter,
        owner=proxy_submitter,
        client=client,
        created=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    # 2. Apply SetProxyInformation: David is now submitting for Bob.
    event = SetProxyInformation(
        creator=proxy_submitter,
        proxied_name="Bob Proxied",
        proxied_email="bob@proxied.org",
        proxy_name=proxy_submitter.name,
    )
    event.apply(submission)

    # Sanity check: the event mutated the in-memory submission as expected.
    assert submission.contact_name == "Bob Proxied"
    assert submission.contact_email == "bob@proxied.org"
    assert submission.proxy == "David Submitter"

    # 3. Persist to the legacy DB.
    dbs = _new_db_row()
    dbs.update_from_submission(submission)
    db_session.add(dbs)
    db_session.commit()
    submission_id = dbs.submission_id

    # 4. Reload and rebuild the domain object.
    db_session.expire_all()
    reloaded_row = db_session.get(models.Submission, submission_id)
    rebuilt = to_submission(reloaded_row)

    # 5. Proxied contact and proxy marker survive the round trip.
    assert rebuilt.contact_name == "Bob Proxied"
    assert rebuilt.contact_email == "bob@proxied.org"
    assert rebuilt.proxy == "David Submitter"
    # The user account behind the submission is still David's.
    assert rebuilt.creator.user_id == "123"
