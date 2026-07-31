"""FastAPI application for arXiv's SWORD deposit API.

Run it locally with ``uv run python local_sword.py``.

Two constraints on anything added here:

* **Endpoints that touch the `SubmitApi` must be ``def``, not ``async def``.**
  Sessions are scoped per thread outside Flask, and FastAPI runs ``def``
  endpoints on their own threadpool thread. An ``async def`` endpoint shares the
  event-loop thread with every other request in flight, so they would share one
  SQLAlchemy session. See
  `submit_ce.implementations.legacy_implementation.fastapi_impl`.

* **Session cleanup has to happen on the thread that used the session.**
  ``remove_session()`` acts on the calling thread's session, so calling it from
  async middleware (which runs on the event-loop thread) would release the wrong
  one and leak the endpoint's. Do it inside the endpoint's own ``def``, or via a
  helper that runs there. No DB-backed routes exist yet; this needs settling
  when the deposit routes land.
"""

import logging

from arxiv import db
from arxiv.config import settings as base_settings
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from submit_ce.implementations.legacy_implementation.fastapi_impl import (
    FastapiSubmitImplementation,
)
from submit_ce.implementations.wiring import config_backend_api
from submit_ce.ui.config import settings

logger = logging.getLogger(__name__)


def create_sword_app() -> FastAPI:
    """Build the SWORD FastAPI app with a non-Flask `SubmitApi` on ``app.state``."""
    base_settings.CLASSIC_DB_URI = settings.CLASSIC_DB_URI

    app = FastAPI(
        title="arXiv SWORD deposit API",
        description="SWORD v1 (APP Profile 1.3) deposit interface for arXiv.",
    )

    db.init(settings)
    app.state.api = config_backend_api(
        settings, impl=FastapiSubmitImplementation)

    @app.get("/status", response_class=PlainTextResponse)
    def service_status() -> str:
        """Cheap liveness check, matching the UI's ``/status``.

        Deliberately does no I/O: this is what the platform polls. For a real
        backend check call ``app.state.api.healthy()`` -- ``local_sword.py``
        does that once at startup.
        """
        return "ok"

    # SWORD routes (servicedocument, collections, edit, resolve) are added in
    # later steps of the plan.

    return app
