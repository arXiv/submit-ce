"""Loading a version that has no event rows of its own.

``store_event`` stamps each event with ``event.submission_id``, which for
`CreateSubmissionVersion` is the submission being *versioned* -- so classic's
``rep`` row is created with no events under its own id. Loading it by that id
reported a row that plainly exists as missing, which is why a paper could not be
replaced twice.
"""

import arxiv.db.models as models
import pytest
from arxiv.db import Session

from submit_ce.domain.exceptions import NoSuchSubmission
from submit_ce.implementations.legacy_implementation import db

PAPER = "2607.55555"


@pytest.fixture
def classic_db():
    """An empty legacy schema on sqlite, bound to `arxiv.db.Session`.

    Same shape as ``submit_ce/sword/tests/conftest.py``'s ``sword_db``; repeated
    here because these tests sit with the shared code they exercise rather than
    with SWORD.
    """
    import shutil
    import tempfile
    from pathlib import Path

    from arxiv.db import session_factory

    from submit_ce.make_test_db import create_all_db
    from submit_ce.ui.config import settings

    tmp = tempfile.mkdtemp()
    engine, url, _path = create_all_db(str(Path(tmp) / "legacy.db"))
    previous = settings.CLASSIC_DB_URI
    settings.CLASSIC_DB_URI = url
    session_factory.configure(bind=engine)
    Session.remove()
    try:
        yield engine
    finally:
        Session.remove()
        settings.CLASSIC_DB_URI = previous
        shutil.rmtree(tmp, ignore_errors=True)


def _row(session, **kwargs):
    # remote_addr, remote_host and package are NOT NULL with a FetchedValue()
    # server default: MySQL fills them from DDL, sqlite has nothing to fall back
    # on, so they have to be supplied here.
    fields = dict(remote_addr="10.0.0.1", remote_host="h", package="",
                  submitter_id=55596, status=7, type="new")
    fields.update(kwargs)
    row = models.Submission(**fields)
    session.add(row)
    session.flush()
    return row


@pytest.fixture
def family(classic_db):
    """An announced v1 and a v2 that owns no events, as a replacement leaves it."""
    origin = _row(Session, version=1, doc_paper_id=PAPER)
    later = _row(Session, version=2, doc_paper_id=PAPER, type="rep", status=0)
    Session.commit()
    return origin, later


def test_a_row_with_no_family_yields_nothing(classic_db):
    """No doc_paper_id means nothing to group by."""
    orphan = _row(Session, version=1)
    Session.commit()
    assert db.get_family_events(Session, orphan) == []


def test_the_origin_consults_no_one(family):
    """The first row *is* the origin; falling back to itself would loop."""
    origin, _later = family
    assert db.get_family_events(Session, origin) == []


def test_a_later_version_looks_up_the_origin(family):
    """The lookup itself, without events present: an empty log, not an error."""
    _origin, later = family
    assert db.get_family_events(Session, later) == []


def test_loading_a_version_without_events_still_raises_when_the_family_has_none(
        family):
    """The fallback must not turn a genuinely missing submission into an empty one.

    A row whose family has no events anywhere is indistinguishable from a bad id,
    and reporting it as an empty submission would hide the problem.
    """
    from submit_ce.implementations.legacy_implementation import (
        LegacySubmitImplementation,
    )
    _origin, later = family
    impl = LegacySubmitImplementation.__new__(LegacySubmitImplementation)
    with pytest.raises(NoSuchSubmission):
        impl._load(Session, str(later.submission_id))
