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

Request bodies arrive as a declared ``bytes`` parameter rather than via
``await request.body()`` -- FastAPI reads them on the event loop before handing off
to the threadpool, which a sync endpoint cannot do for itself.
"""

import logging
from contextlib import contextmanager

from arxiv import db
from arxiv.config import settings as base_settings
from arxiv.taxonomy.definitions import GROUPS
from fastapi import Body, Depends, FastAPI, Request, Response
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
from submit_ce.sword.atom.render import (
    ENTRY_CONTENT_TYPE,
    ERROR_CONTENT_TYPE,
    render_error,
    render_media_entry,
)
from submit_ce.sword.atom.servicedoc import (
    SERVICE_DOCUMENT_CONTENT_TYPE,
    render_service_document,
)
from submit_ce.sword.deposits import (
    ATOM_ENTRY_TYPE,
    DepositStore,
    InMemoryDepositStore,
)
from submit_ce.sword.errors import SwordFault
from submit_ce.sword.request import parse_deposit_headers, verify_md5
from submit_ce.ui.config import settings

logger = logging.getLogger(__name__)

ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "DELETE"})
"""``AtomPP.pm:147-153``: anything else is 405 with a plain-text body."""

DEPOSIT_PREFIX = "sword-deposits"

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


def build_deposit_store(config) -> DepositStore:
    """Choose a deposit staging store from settings.

    Follows the same ``STORE`` switch as `config_backend_api`. The in-memory store
    keeps nothing across a restart, which matches what ``STORE=null`` means
    elsewhere in submit-ce.
    """
    if config.STORE == "gs":
        from submit_ce.sword.gs_deposits import GsDepositStore
        prefix = "/".join(part for part in (config.STORE_GS_PREFIX,
                                           DEPOSIT_PREFIX) if part)
        logger.info("SWORD deposits in gs://%s/%s",
                    config.STORE_GS_BUCKET, prefix)
        return GsDepositStore(gs_bucket=config.STORE_GS_BUCKET,
                              gs_prefix=prefix)
    logger.warning("STORE=%s: SWORD deposits are in memory and will not "
                   "survive a restart", config.STORE)
    return InMemoryDepositStore()


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
    app.state.deposits = build_deposit_store(settings)
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

    @app.post("/sword-app/{collection}-collection")
    def deposit(
            collection: str,
            request: Request,
            payload: bytes = Body(default=b"",
                                  media_type="application/octet-stream"),
            credentials: HTTPBasicCredentials = Depends(_basic),
    ) -> Response:
        """Deposit media into a collection.

        Check order follows ``AtomPP.pm:218-343``: credentials, collection,
        permission, SWORD headers, checksum, then id allocation.
        """
        site = request.app.state.site
        if credentials is None:
            raise SwordFault("EAUTH", "no credentials")

        headers = parse_deposit_headers(request.headers)

        with sword_session() as session:
            depositor = sword_auth.depositor_from_credentials(
                session, credentials.username, credentials.password, site)

            # An unknown collection is EVCOL. Legacy reached EAUTH instead,
            # because it tested group permission first using a substring regex
            # that no bogus name could match (AtomPP.pm:222-236) -- which makes
            # the EVCOL example at submit_sword.md:845-875 unreachable. The
            # documented behaviour is the one implemented.
            if not sword_collections.is_valid_collection(collection):
                raise SwordFault("EVCOL", collection)
            if not sword_collections.user_may_post_to(
                    session, depositor.user_id, collection):
                raise SwordFault("EAUTH", f"posting to '{collection}'")

            if headers.contact_email and sword_auth.is_suspect_email(
                    session, headers.contact_email):
                raise SwordFault(
                    "EVCML",
                    "arXiv does not accept third party submission for "
                    "X-On-Behalf-Of author, author must submit directly")

        verify_md5(payload, headers.md5)

        if headers.content_type.split(";", 1)[0].strip() == ATOM_ENTRY_TYPE:
            # TODO(step 10): a wrapper deposit creates the submission.
            raise SwordFault(
                "EIMPL", "metadata wrapper deposits are not yet available")

        store = request.app.state.deposits
        deposit_id = store.allocate_id()
        store.save(deposit_id, depositor.nickname, headers.content_type, payload)

        entry = render_media_entry(
            deposit_id=deposit_id,
            depositor=depositor.nickname,
            content_type=headers.content_type,
            collection=collection,
            group_name=GROUPS[sword_collections.group_id(collection)].full_name,
            site=site,
            contact_name=headers.contact_name,
            contact_email=headers.contact_email,
            no_op=headers.no_op,
            verbose=headers.verbose,
            packaging=headers.packaging,
            user_agent=headers.user_agent,
        )
        store.save_entry(deposit_id, entry)

        # A no-op deposit answers 200 and sends no Location
        # (``AtomPP.pm:318,678``).
        response_headers = {}
        if not headers.no_op:
            response_headers["Location"] = \
                f"https://{site}/sword-app/getid/app/{deposit_id}"
        if headers.filename:
            response_headers["Content-Disposition"] = headers.filename

        return Response(content=entry,
                        status_code=200 if headers.no_op else 201,
                        media_type=ENTRY_CONTENT_TYPE,
                        headers=response_headers)

    # Remaining routes (getid/edit GET, PUT replacement, resolve) arrive in
    # later steps.

    return app
