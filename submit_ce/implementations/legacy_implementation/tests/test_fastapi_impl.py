"""The `SubmitApi` must work with no Flask app context.

The SWORD service (SUBMISSION-29) runs under FastAPI, where there is no Flask
app context at all. These tests pin the two things that makes possible:

* `FastapiSubmitImplementation` can persist events -- i.e. nothing in the save
  path reaches for ``flask.current_app`` or an app context.
* `arxiv.db.Session` scopes per thread once Flask is out of the picture, which
  is what gives FastAPI's synchronous endpoints one session per request.
"""

import shutil
import tempfile
import threading
from pathlib import Path

import pytest
from arxiv.db import Session, session_factory
from flask import has_app_context

from submit_ce.domain.agent import InternalClient, PublicUser
from submit_ce.domain.event import CreateSubmission
from submit_ce.implementations import NullFileStore
from submit_ce.implementations.legacy_implementation.fastapi_impl import (
    FastapiSubmitImplementation,
    fastapi_get_session,
    remove_session,
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


def test_save_create_submission_without_flask_app_context(legacy_sqlite):
    """A submission can be created with no Flask app context in play."""
    assert not has_app_context()

    api = FastapiSubmitImplementation(store=NullFileStore())
    user = PublicUser(user_id="1234", name="A Depositor", email="dep@example.org")
    client = InternalClient(name="test_fastapi_impl")

    submission, events = api.save(CreateSubmission(creator=user, client=client))

    assert not has_app_context(), "save() must not create a Flask app context"
    assert submission.submission_id
    assert events


def test_saved_submission_is_readable_back(legacy_sqlite):
    """get_with_history round-trips outside Flask too."""
    api = FastapiSubmitImplementation(store=NullFileStore())
    user = PublicUser(user_id="1234", name="A Depositor", email="dep@example.org")
    client = InternalClient(name="test_fastapi_impl")

    submission, _ = api.save(CreateSubmission(creator=user, client=client))
    loaded, history = api.get_with_history(str(submission.submission_id))

    # Compared as strings: save() reports submission_id as an int while
    # get_with_history() reports it as a str. That pre-existing inconsistency
    # is not what this test is about.
    assert str(loaded.submission_id) == str(submission.submission_id)
    assert history


def test_get_session_is_stable_within_one_scope(legacy_sqlite):
    """Repeated calls in the same scope must return the same session.

    `LegacySubmitImplementation` calls ``get_session()`` several times per
    save(), so a provider handing out fresh sessions would split a single
    save across transactions.
    """
    assert fastapi_get_session() is fastapi_get_session()


def test_remove_session_starts_a_fresh_session(legacy_sqlite):
    """`remove_session` is what stops a request inheriting the previous one."""
    first = fastapi_get_session()
    remove_session()
    assert fastapi_get_session() is not first


def test_sessions_are_scoped_per_thread(legacy_sqlite):
    """Thread scoping is what makes FastAPI's sync endpoints request-isolated."""
    seen: dict[str, object] = {}

    def grab(key: str) -> None:
        seen[key] = fastapi_get_session()
        remove_session()

    for key in ("a", "b"):
        thread = threading.Thread(target=grab, args=(key,))
        thread.start()
        thread.join()

    assert seen["a"] is not seen["b"]
