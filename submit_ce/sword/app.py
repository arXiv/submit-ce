"""FastAPI application for arXiv's SWORD deposit API.

Run it locally with ``uv run python local_sword.py``.

Endpoints that touch the database must be ``def``, not ``async def``. Sessions are
scoped per thread outside Flask, and FastAPI runs ``def`` endpoints on their own
threadpool thread; an ``async def`` endpoint shares the event-loop thread with
every other request in flight, so they would share one SQLAlchemy session. See
`submit_ce.implementations.legacy_implementation.fastapi_impl`.

For the same reason the session is released *inside* the endpoint via
`sword_session`, not in middleware: ``remove_session()`` acts on the calling
thread, so releasing from the event loop would drop the wrong session and leak the
endpoint's.
"""

import logging
from contextlib import contextmanager

from arxiv import db
from arxiv.config import settings as base_settings
from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import PlainTextResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from submit_ce.implementations.legacy_implementation.fastapi_impl import (
    FastapiSubmitImplementation,
    fastapi_get_session,
    remove_session,
)
from submit_ce.implementations.wiring import config_backend_api
from submit_ce.sword import auth as sword_auth
from submit_ce.sword import collections as sword_collections
from submit_ce.sword.atom.render import ERROR_CONTENT_TYPE, render_error
from submit_ce.sword.atom.servicedoc import (
    SERVICE_DOCUMENT_CONTENT_TYPE,
    render_service_document,
)
from submit_ce.sword.errors import SwordFault
from submit_ce.ui.config import settings

logger = logging.getLogger(__name__)

ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "DELETE"})
"""``AtomPP.pm:147-153``: anything else is 405 with a plain-text body."""

# `auto_error=False` so a missing or malformed Authorization header reaches our
# own handler and comes back as a sword:error with the realm challenge, rather
# than FastAPI's JSON detail.
_basic = HTTPBasic(realm=sword_auth.REALM, auto_error=False)


@contextmanager
def sword_session():
    """A SQLAlchemy session for one request, released on this thread."""
    try:
        yield fastapi_get_session()
    finally:
        remove_session()


def error_response(fault: SwordFault, site: str) -> Response:
    """Render a `SwordFault` as its ``sword:error`` document."""
    headers = {}
    if fault.error.mnemonic == "EAUTH":
        headers["WWW-Authenticate"] = sword_auth.WWW_AUTHENTICATE
    return Response(content=render_error(fault, site=site),
                    status_code=fault.status,
                    media_type=ERROR_CONTENT_TYPE,
                    headers=headers)


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
    app.state.site = settings.BASE_SERVER

    @app.exception_handler(SwordFault)
    def _sword_fault_handler(request: Request, fault: SwordFault) -> Response:
        return error_response(fault, request.app.state.site)

    @app.middleware("http")
    async def _reject_unsupported_methods(request: Request, call_next):
        """405 for anything outside GET/POST/PUT/DELETE.

        Legacy answers with the bare string ``unsupported`` rather than XML
        (``AtomPP.pm:151``), which is reproduced here.
        """
        if request.method not in ALLOWED_METHODS:
            return PlainTextResponse("unsupported", status_code=405)
        return await call_next(request)

    @app.get("/status", response_class=PlainTextResponse)
    def service_status() -> str:
        """Cheap liveness check, matching the UI's ``/status``.

        Deliberately does no I/O: this is what the platform polls. For a real
        backend check call ``app.state.api.healthy()`` -- ``local_sword.py`` does
        that once at startup.
        """
        return "ok"

    @app.get("/sword-app/servicedocument")
    def servicedocument(
            request: Request,
            credentials: HTTPBasicCredentials = Depends(_basic),
    ) -> Response:
        """The per-depositor service document.

        ``X-On-Behalf-Of`` names a *nickname* here (not a contact author as it
        does on a deposit), and the response describes that user's collections
        (``AtomPP.pm:352-366``).
        """
        site = request.app.state.site
        if credentials is None:
            raise SwordFault("EAUTH", "no credentials")

        with sword_session() as session:
            depositor = sword_auth.depositor_from_credentials(
                session, credentials.username, credentials.password, site)

            mediated = sword_auth.resolve_on_behalf_of(
                session, request.headers.get("X-On-Behalf-Of"))
            if mediated is not None:
                group_ids = sword_collections.groups_for_user(session, mediated)
            else:
                group_ids = depositor.groups

            document = render_service_document(group_ids=group_ids, site=site)

        return Response(
            content=document,
            media_type=SERVICE_DOCUMENT_CONTENT_TYPE,
            # Legacy sets a relative one-day expiry (AtomPP.pm:365); the manual
            # tells depositors to re-check about daily (submit_sword.md:296-299).
            headers={"Cache-Control": "max-age=86400"},
        )

    # Deposit routes (collections, edit, resolve) arrive in later steps.

    return app
