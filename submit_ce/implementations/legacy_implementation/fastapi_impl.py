"""`SubmitApi` implementation for use from a FastAPI (non-Flask) process.

`arxiv.db.Session` is a `scoped_session` whose scope function returns the
current Flask app-context id when there is one, and the current thread id
otherwise (see `arxiv.db.__init__`). So the same registry works here without
Flask: each thread gets its own session.

That gives one session per request only for **synchronous** (``def``) endpoints,
which FastAPI runs on a threadpool thread. ``async def`` endpoints all share the
event-loop thread and would therefore share a single session across concurrent
requests, which is not safe. Define endpoints that touch the `SubmitApi` with
``def``.

Callers must call `remove_session()` when a request finishes, the way the Flask
app does in its ``teardown_appcontext`` hook (see `submit_ce.ui.factory`).
Otherwise the session stays bound to the threadpool thread and is silently
reused by whatever request lands on that thread next.
"""

from arxiv.db import Session
from sqlalchemy.orm import Session as SqlalchemySession

from . import LegacySubmitImplementation
from submit_ce.implementations.compile.compile_api_service import CompileApiService


def fastapi_get_session() -> SqlalchemySession:
    """Gets a SQLAlchemy session; thread-scoped when there is no Flask app context."""
    return Session()


def remove_session() -> None:
    """Discard the current scope's session. Call at the end of every request."""
    Session.remove()


class FastapiSubmitImplementation(LegacySubmitImplementation):
    """Implementation of the `SubmitApi` usable without Flask."""

    def __init__(self,
                 store,
                 compiler=None,
                 email_service=None,
                 config=None,
                 participants=None,
    ):
        from submit_ce.domain.config import SubmitConfig
        from submit_ce.implementations import NullEmailService
        super().__init__(
            store=store,
            compiler=compiler or CompileApiService(),
            email_service=email_service or NullEmailService(),
            config=config or SubmitConfig(),
            get_session=fastapi_get_session,
            participants=participants,
        )
