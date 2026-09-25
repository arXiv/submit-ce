"""FastAPI application for the arXiv submission mutation API (SUBMISSION-257).

Run locally with ``uv run python local_api.py`` (see that file).

Endpoints that touch the database are ``def``, not ``async def``: sessions are
thread-scoped outside Flask and FastAPI runs ``def`` endpoints on their own
threadpool thread, so each request gets its own SQLAlchemy session. The session
is released per-request by the ``api_session`` dependency (``remove_session()``
acts on the calling thread, so it must run on the request's thread). Same
reasoning as `submit_ce.sword.app`.
"""
import logging

from fastapi import Depends, FastAPI
from fastapi.responses import PlainTextResponse

from arxiv import db
from arxiv.config import settings as base_settings

from submit_ce.implementations.wiring import config_backend_api
from submit_ce.implementations.legacy_implementation.fastapi_impl import (
    FastapiSubmitImplementation,
    fastapi_get_session,
    remove_session,
)
from submit_ce.ui.config import settings
from submit_ce.fastapi.routes import router

logger = logging.getLogger(__name__)


def api_session():
    """Per-request SQLAlchemy session, released on this (threadpool) thread."""
    try:
        yield fastapi_get_session()
    finally:
        remove_session()


def create_api_app() -> FastAPI:
    """Build the submission mutation API app with a non-Flask `SubmitApi`."""
    base_settings.CLASSIC_DB_URI = settings.CLASSIC_DB_URI

    # Interactive docs are useful on a laptop and are new attack surface anywhere
    # else; gate them on LOCAL_LOGIN like the SWORD app does.
    local = settings.LOCAL_LOGIN
    app = FastAPI(
        title="arXiv submission mutation API",
        description="REST endpoints for services (e.g. arxiv-check) to mutate "
                    "submissions through the Submit 2.0 event model.",
        version="0.1.0",
        docs_url="/docs" if local else None,
        redoc_url="/redoc" if local else None,
        openapi_url="/openapi.json" if local else None,
    )

    db.init(settings)
    app.state.api = config_backend_api(settings, impl=FastapiSubmitImplementation)

    @app.get("/status", response_class=PlainTextResponse)
    def service_status() -> str:
        """Cheap liveness check; does no I/O."""
        return "ok"

    app.include_router(router, dependencies=[Depends(api_session)])
    return app
