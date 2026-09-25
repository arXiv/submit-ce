"""Save-side round-trip for admin remove / unremove (SUBMISSION-257).

The event unit tests cover the domain projection; this pins the *persistence*
mapping and the audit trail the endpoints rely on:

* after `save()` the classic ``arXiv_submissions`` row carries status REMOVED (9)
  for a remove and ON_HOLD (2) for an unremove -- what legacy consumers (1.5,
  modapi, arxiv-check) see;
* each action writes an ``arXiv_admin_log`` row, with the optional comment,
  matching what moderators/arxiv-check read for the history.

Uses the same no-Flask sqlite setup as ``test_fastapi_impl``.
"""
import shutil
import tempfile
from pathlib import Path

import pytest
from arxiv.db import Session, session_factory

from submit_ce.domain.agent import InternalClient, PublicUser
from submit_ce.domain.event import CreateSubmission, AdminRemove, UnRemove
from submit_ce.implementations import NullFileStore
from submit_ce.implementations.legacy_implementation import models as legacy_models
from submit_ce.implementations.legacy_implementation.fastapi_impl import (
    FastapiSubmitImplementation,
)
from submit_ce.make_test_db import create_all_db


@pytest.fixture
def legacy_sqlite():
    """Bind `arxiv.db.Session` to an empty legacy sqlite schema."""
    tmp = tempfile.mkdtemp()
    engine, _url, _path = create_all_db(str(Path(tmp) / "legacy.db"))
    session_factory.configure(bind=engine)
    Session.remove()
    yield engine
    Session.remove()
    shutil.rmtree(tmp, ignore_errors=True)


def _classic_status(submission_id: str) -> int:
    """Read the raw classic status column straight from the DB (no replay)."""
    Session.expire_all()
    row = (Session.query(legacy_models.Submission)
           .filter(legacy_models.Submission.submission_id == int(submission_id))
           .one())
    return row.status


def _admin_log_texts() -> list:
    Session.expire_all()
    return [e.logtext for e in Session.query(legacy_models.AdminLogEntry).all()]


def test_remove_then_unremove_write_classic_status_and_log(legacy_sqlite):
    api = FastapiSubmitImplementation(store=NullFileStore())
    user = PublicUser(user_id="1234", name="A Depositor", email="dep@example.org")
    client = InternalClient(name="test_remove_roundtrip")

    submission, _ = api.save(CreateSubmission(creator=user, client=client))
    sid = str(submission.submission_id)

    # remove -> classic REMOVED (9) + admin-log row carrying the comment
    api.save(AdminRemove(creator=user, client=client, comment="spam"),
             submission_id=sid)
    assert _classic_status(sid) == legacy_models.Submission.REMOVED  # 9
    assert any("Remove: spam" in t for t in _admin_log_texts())

    # unremove -> classic ON_HOLD (2) + admin-log row
    api.save(UnRemove(creator=user, client=client, comment="cleared"),
             submission_id=sid)
    assert _classic_status(sid) == legacy_models.Submission.ON_HOLD  # 2
    assert any("Unremove: cleared" in t for t in _admin_log_texts())
