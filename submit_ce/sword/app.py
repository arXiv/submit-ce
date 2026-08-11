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
from submit_ce.domain.agent import HttpClient, PublicUser
from submit_ce.implementations.wiring import config_backend_api
from submit_ce.sword import auth as sword_auth
from submit_ce.sword import collections as sword_collections
from submit_ce.sword import replace as sword_replace
from submit_ce.sword.atom.parse import parse_wrapper
from submit_ce.sword.atom.render import (
    ENTRY_CONTENT_TYPE,
    ERROR_CONTENT_TYPE,
    render_error,
    render_media_entry,
    render_wrapper_entry,
)
from submit_ce.sword.ingest import ingest_replacement, ingest_wrapper
from submit_ce.sword.tracking import (
    CONTENT_TYPE as TRACKING_CONTENT_TYPE,
    render_deposit,
    resolve_deposit,
)
from submit_ce.sword.atom.servicedoc import (
    SERVICE_DOCUMENT_CONTENT_TYPE,
    render_service_document,
)
from submit_ce.sword.deposits import (
    ATOM_ENTRY_TYPE,
    DepositStore,
    InMemoryDepositStore,
    check_deposit_size,
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

    Exhaustive on ``STORE``, like `config_backend_api`: an unrecognized value
    raises rather than falling through. Defaulting to the in-memory store would be
    the worst possible failure -- media deposits answer 201 while the bytes live
    only in one process's heap, so they vanish on restart, the id counter restarts
    and reissues ids already handed out, and a wrapper request routed to another
    instance cannot see the media it references.
    """
    if config.STORE == "gs":
        from submit_ce.sword.gs_deposits import GsDepositStore
        prefix = "/".join(part for part in (config.STORE_GS_PREFIX,
                                           DEPOSIT_PREFIX) if part)
        logger.info("SWORD deposits in gs://%s/%s",
                    config.STORE_GS_BUCKET, prefix)
        return GsDepositStore(gs_bucket=config.STORE_GS_BUCKET,
                              gs_prefix=prefix)
    if config.STORE == "null":
        logger.warning("STORE=null: SWORD deposits are in memory, are not "
                       "shared between instances, and will not survive a "
                       "restart")
        return InMemoryDepositStore()
    raise NotImplementedError(
        f"STORE={config.STORE!r} has no SWORD deposit store. Add one here "
        f"rather than letting deposits fall back to memory.")


def request_base_url(request: Request) -> str:
    """Scheme and host this request actually arrived on, e.g. ``https://arxiv.org``.

    Every link the API makes to *itself* -- ``edit``, ``edit-media``,
    ``rel="alternate"``, collection hrefs, ``Location`` -- is built from this rather
    than from a configured hostname, so a depositor is told about the host they
    reached. arXiv serves SWORD on more than one name (``arxiv.org``,
    ``export.arxiv.org``, ``dev.arxiv.org``), and on a developer's laptop it is
    ``localhost:8001``; a fixed ``BASE_SERVER`` gets all of those wrong.

    Legacy used a config constant, ``$THIS_SITE`` (``AtomPP.pm``), but its own
    tracking controller derived the URI from the request instead
    (``Controller/Sword.pm:27``, Catalyst ``uri_for``). This follows the latter
    throughout.

    ``X-Forwarded-Proto``/``-Host`` win when present -- Cloud Run sets them, and the
    container itself only ever sees plain http on :8080.

    Links to arXiv *as a service* -- the help page, an archive's abstract, the
    ``sword_errors`` anchors, ``/sword-license`` -- are not self-links and keep using
    the configured public host.
    """
    def first(value: str) -> str:
        return value.split(",")[0].strip()

    forwarded_proto = request.headers.get("X-Forwarded-Proto")
    scheme = first(forwarded_proto) if forwarded_proto else request.url.scheme

    forwarded_host = request.headers.get("X-Forwarded-Host")
    host = (first(forwarded_host) if forwarded_host
            else request.headers.get("Host") or request.url.netloc)

    return f"{scheme}://{host}"


def error_response(fault: SwordFault, base_url: str, site: str) -> Response:
    """Render a `SwordFault` as its ``sword:error`` document."""
    headers = {}
    if fault.error.mnemonic == "EAUTH":
        headers["WWW-Authenticate"] = sword_auth.WWW_AUTHENTICATE
    return Response(content=render_error(fault, base_url=base_url, site=site),
                    status_code=fault.status,
                    media_type=ERROR_CONTENT_TYPE,
                    headers=headers)


def create_sword_app() -> FastAPI:
    """Build the SWORD FastAPI app with a non-Flask `SubmitApi` on ``app.state``."""
    base_settings.CLASSIC_DB_URI = settings.CLASSIC_DB_URI

    # FastAPI's interactive docs are useful on a laptop and are new attack surface
    # anywhere else: legacy exposed nothing under the SWORD app unauthenticated,
    # since ``sword.conf`` gated /sword-app at the Apache layer. Passing None
    # removes the routes outright, so they 404 rather than advertising themselves
    # with a 401. ``openapi_url`` matters most of the three -- it is the
    # machine-readable schema, and dropping only the HTML pages would leave it.
    #
    # Gated on LOCAL_LOGIN rather than a flag of its own: it is already this repo's
    # "developer on a laptop" switch and it admits fake sessions, which is strictly
    # more dangerous than a schema page. The tradeoff is that docs cannot be turned
    # on for a deployed instance without also accepting fake logins; that is the
    # safe direction, and a separate setting can be added if it is ever wanted.
    local = settings.LOCAL_LOGIN
    app = FastAPI(
        title="arXiv SWORD deposit API",
        description="SWORD v1 (APP Profile 1.3) deposit interface for arXiv.",
        docs_url="/docs" if local else None,
        redoc_url="/redoc" if local else None,
        openapi_url="/openapi.json" if local else None,
    )

    db.init(settings)
    app.state.api = config_backend_api(
        settings, impl=FastapiSubmitImplementation)
    app.state.deposits = build_deposit_store(settings)
    app.state.site = settings.BASE_SERVER

    @app.exception_handler(SwordFault)
    def _sword_fault_handler(request: Request, fault: SwordFault) -> Response:
        return error_response(fault, request_base_url(request),
                              request.app.state.site)

    @app.exception_handler(Exception)
    def _unexpected_error_handler(request: Request,
                                  exc: Exception) -> Response:
        """Render anything that is not a `SwordFault` as one anyway.

        Without this, an exception from the domain or database layer reaches
        Starlette's default 500 handler and the depositor gets an HTML body. Every
        SWORD client parses the response as XML, so an unhandled error is
        indistinguishable to it from a malformed server.

        The path that prompted this -- replacing a paper whose previous replacement
        was not announced yet, which raised `NoSuchSubmission` from the event store
        -- is now refused up front with EPSUB (`replace.pending_submission_id`). This
        stays as the backstop for the ones not yet found.

        ENAVL rather than a 500 code because the legacy set has none, this is what
        legacy answered when it could not proceed internally (``AtomPP.pm:258,501``),
        and 503 tells an automated depositor to retry rather than to treat the
        deposit as permanently refused.

        The exception never reaches the client: the traceback is logged, and the
        response carries only the fixed message. Depositors are third parties, so
        internal detail is not theirs to see.
        """
        # exc_info=exc, not logger.exception(): this handler is sync, so Starlette
        # runs it in a threadpool where sys.exc_info() is empty and the traceback
        # would be logged as "NoneType: None". Passing the exception is what makes
        # withholding it from the response an acceptable trade.
        logger.error("unhandled error in %s %s", request.method,
                     request.url.path, exc_info=exc)
        fault = SwordFault("ENAVL", "unexpected error handling the request")
        return error_response(fault, request_base_url(request),
                              request.app.state.site)

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
        base_url = request_base_url(request)
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

            document = render_service_document(
                group_ids=group_ids, base_url=base_url, main_site=site)

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
        base_url = request_base_url(request)
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

        # Before the checksum, so an oversize body is not hashed first, and before
        # the dispatch below, so a wrapper is capped as well as media.
        check_deposit_size(payload)
        verify_md5(payload, headers.md5)

        store = request.app.state.deposits

        if headers.content_type.split(";", 1)[0].strip() == ATOM_ENTRY_TYPE:
            return _deposit_wrapper(request, collection, payload, headers,
                                    credentials, site, base_url)

        deposit_id = store.allocate_id()
        store.save(deposit_id, depositor.nickname, headers.content_type, payload)

        entry = render_media_entry(
            deposit_id=deposit_id,
            depositor=depositor.nickname,
            content_type=headers.content_type,
            collection=collection,
            group_name=GROUPS[sword_collections.group_id(collection)].full_name,
            base_url=base_url,
            contact_name=headers.contact_name,
            contact_email=headers.contact_email,
            no_op=headers.no_op,
            verbose=headers.verbose,
            packaging=headers.packaging,
            user_agent=headers.user_agent,
        )
        store.save_entry(deposit_id, entry, owner=depositor.nickname)

        # A no-op deposit answers 200 and sends no Location
        # (``AtomPP.pm:318,678``).
        response_headers = {}
        if not headers.no_op:
            response_headers["Location"] = \
                f"{base_url}/sword-app/getid/app/{deposit_id}"
        if headers.filename:
            response_headers["Content-Disposition"] = headers.filename

        return Response(content=entry,
                        status_code=200 if headers.no_op else 201,
                        media_type=ENTRY_CONTENT_TYPE,
                        headers=response_headers)

    @app.get("/sword-app/getid/app/{deposit_id}")
    @app.get("/sword-app/edit/{deposit_id}.atom")
    def get_entry(
            deposit_id: str,
            request: Request,
            credentials: HTTPBasicCredentials = Depends(_basic),
    ) -> Response:
        """Re-serve a stored deposit entry, owner-checked.

        ``AtomPP.pm:367-394``. Both paths serve the same document; the ``.atom``
        form is the ``rel="edit"`` href a deposit response hands back.
        """
        site = request.app.state.site
        if credentials is None:
            raise SwordFault("EAUTH", "no credentials")

        with sword_session() as session:
            depositor = sword_auth.depositor_from_credentials(
                session, credentials.username, credentials.password, site)

        store = request.app.state.deposits
        entry = store.read_entry(deposit_id)
        if entry is None:
            raise SwordFault("ENMDI", f"info:arxiv/app/{deposit_id}")
        if not store.owned_by(deposit_id, depositor.nickname):
            raise SwordFault("ENOWN")

        return Response(content=entry, media_type=ENTRY_CONTENT_TYPE,
                        headers={"Cache-Control": "max-age=86400"})

    @app.get("/sword-app/edit/{rest:path}")
    def get_edit_other(rest: str) -> Response:
        """Anything else under ``/edit/`` is EBLOG (``AtomPP.pm:395-399``).

        The message names the real cause: an ``/edit`` GET only works on the
        ``rel="edit"`` href, not on ``rel="edit-media"``.
        """
        raise SwordFault("EBLOG", f"GET /sword-app/edit/{rest}")

    @app.get("/sword-app/{collection}-collection")
    def get_collection(collection: str) -> Response:
        """A collection is POST-only (``AtomPP.pm:400-404``).

        The errortext is legacy's, including its note about the 1.0-to-1.1 path
        change, because a client hitting this is misconfigured and the hint is the
        useful part.
        """
        raise SwordFault(
            "EGTPT",
            f"GET /sword-app/{collection}-collection\n"
            "If you reached this message via a POST to /app, you must use "
            "/sword-app instead(change between SWORD APP profile 1.0 and 1.1).\n"
            "POST message content will not be redirected due to security concerns")

    @app.put("/sword-app/edit/{target:path}")
    def replace(
            target: str,
            request: Request,
            payload: bytes = Body(default=b"",
                                  media_type="application/octet-stream"),
            credentials: HTTPBasicCredentials = Depends(_basic),
    ) -> Response:
        """Replace an announced paper with a new version.

        Check order follows ``AtomPP.pm:413-531``: identifier, ownership, content
        type, SWORD headers, checksum, then the wrapper itself.
        """
        site = request.app.state.site
        base_url = request_base_url(request)
        if credentials is None:
            raise SwordFault("EAUTH", "no credentials")

        store = request.app.state.deposits
        api = request.app.state.api

        with sword_session() as session:
            depositor = sword_auth.depositor_from_credentials(
                session, credentials.username, credentials.password, site)

            paper_id = sword_replace.resolve_target(session, target)
            sword_replace.require_owner(session, paper_id, depositor.nickname)

            content_type = (request.headers.get("Content-Type") or "").split(
                ";", 1)[0].strip()
            if content_type != ATOM_ENTRY_TYPE:
                raise SwordFault(
                    "EMDTP",
                    "PUT to /replace must be of type 'application/atom+xml'")

            headers = parse_deposit_headers(request.headers)
            check_deposit_size(payload)
            verify_md5(payload, headers.md5)

            # Refuse before doing any work if a version is already open. Checked
            # after ownership so only an owner learns about the paper's state.
            pending = sword_replace.pending_submission_id(session, paper_id)
            if pending is not None:
                raise SwordFault(
                    "EPSUB",
                    f"'{paper_id}' already has submission {pending} in progress")

            submission_id = sword_replace.announced_submission_id(
                session, paper_id)
            if submission_id is None:
                raise SwordFault("ENVID", f"no submission for '{paper_id}'")

            contact_override = None
            if headers.contact_email:
                contact_override = (headers.contact_name, headers.contact_email)

            metadata = parse_wrapper(
                payload,
                collection=None,
                depositor=depositor.nickname,
                contact_override=contact_override,
                is_suspect_email=lambda email: sword_auth.is_suspect_email(
                    session, email),
                deposit_extensions=store.extensions,
                deposit_owner=lambda did: (
                    store.get(did).owner if store.get(did) else None),
                replacing=True,
                existing_categories=sword_replace.existing_categories(
                    session, paper_id),
            )

            sword_id = store.allocate_id()

            entry = render_wrapper_entry(
                deposit_id=sword_id,
                depositor=depositor.nickname,
                summary=metadata.summary,
                primary_category=metadata.primary_category,
                secondary_categories=metadata.secondary_categories,
                base_url=base_url,
                contact_name=metadata.contact_name,
                contact_email=metadata.contact_email,
                no_op=headers.no_op,
                verbose=headers.verbose,
                packaging=headers.packaging,
                user_agent=headers.user_agent,
                replacing=True,
            )

            if not headers.no_op:
                endorsements = sword_collections.endorsement_wildcards(
                    session, depositor.user_id)
                ingest_replacement(api, store, session, metadata,
                                   creator=depositor_user(depositor,
                                                          endorsements),
                                   client=deposit_client(request, headers),
                                   depositor=depositor.nickname,
                                   license_uri=depositor.license,
                                   sword_id=sword_id,
                                   submission_id=submission_id)
                store.save_entry(sword_id, entry,
                                 owner=depositor.nickname)

        response_headers = {}
        if not headers.no_op:
            response_headers["Location"] = \
                f"{base_url}/sword-app/getid/app/{sword_id}"

        return Response(content=entry,
                        status_code=200 if headers.no_op else 202,
                        media_type=ENTRY_CONTENT_TYPE,
                        headers=response_headers)

    @app.put("/sword-app/{rest:path}")
    def put_elsewhere(rest: str) -> Response:
        """PUT is only meaningful under ``/edit/`` (``AtomPP.pm:416-422``)."""
        raise SwordFault("EIMPL", f"PUT /sword-app/{rest}")

    @app.delete("/sword-app/{rest:path}")
    def delete_anything(rest: str) -> Response:
        """There are no valid DELETE actions (``AtomPP.pm:539-546``)."""
        raise SwordFault("EIMPL", f"DELETE /sword-app/{rest}")

    @app.get("/sword-app/{rest:path}")
    def get_elsewhere(rest: str) -> Response:
        """Unrecognized GET (``AtomPP.pm:405-410``)."""
        raise SwordFault("EVGRQ", f"GET /sword-app/{rest}")

    @app.get("/resolve/app/{sword_id}")
    def resolve(sword_id: int, request: Request) -> Response:
        """Deposit tracking, linked from a wrapper's ``rel="alternate"``.

        Unauthenticated, as in legacy: ``sword.conf`` gates ``/sword-app`` but not
        ``/resolve``, and the manual documents a plain GET
        (``submit_sword.md:664``).
        """
        base_url = request_base_url(request)
        with sword_session() as session:
            status = resolve_deposit(session, request.app.state.api,
                                    sword_id, base_url)
        return Response(content=render_deposit(status),
                        media_type=TRACKING_CONTENT_TYPE)

    # Remaining routes (getid/edit GET, PUT replacement) arrive in later steps.

    return app


def _deposit_wrapper(request: Request, collection: str, payload: bytes,
                     headers, credentials, site: str,
                     base_url: str) -> Response:
    """A metadata wrapper: validate it, create the submission, answer 202.

    Called from the collection POST route once the content type marks the body as
    an Atom entry rather than media.
    """
    store = request.app.state.deposits
    api = request.app.state.api

    with sword_session() as session:
        depositor = sword_auth.depositor_from_credentials(
            session, credentials.username, credentials.password, site)

        contact_override = None
        if headers.contact_email:
            contact_override = (headers.contact_name, headers.contact_email)

        metadata = parse_wrapper(
            payload,
            collection=collection,
            depositor=depositor.nickname,
            contact_override=contact_override,
            is_suspect_email=lambda email: sword_auth.is_suspect_email(
                session, email),
            deposit_extensions=store.extensions,
            deposit_owner=lambda deposit_id: (
                store.get(deposit_id).owner if store.get(deposit_id) else None),
        )

        sword_id = store.allocate_id()

        entry = render_wrapper_entry(
            deposit_id=sword_id,
            depositor=depositor.nickname,
            summary=metadata.summary,
            primary_category=metadata.primary_category,
            secondary_categories=metadata.secondary_categories,
            base_url=base_url,
            contact_name=metadata.contact_name,
            contact_email=metadata.contact_email,
            no_op=headers.no_op,
            verbose=headers.verbose,
            packaging=headers.packaging,
            user_agent=headers.user_agent,
        )

        # A true no-op: validated and reported on, nothing created. Legacy still
        # built the submission object before checking the flag
        # (``AtomPP.pm:1280-1291``), so a no-op could leave rows behind; the plan's
        # decision 4 is not to reproduce that.
        if not headers.no_op:
            endorsements = sword_collections.endorsement_wildcards(
                session, depositor.user_id)
            ingest_wrapper(api, store, session, metadata,
                           creator=depositor_user(depositor, endorsements),
                           client=deposit_client(request, headers),
                           depositor=depositor.nickname,
                           license_uri=depositor.license,
                           sword_id=sword_id)
            store.save_entry(sword_id, entry,
                             owner=depositor.nickname)

    response_headers = {}
    if not headers.no_op:
        response_headers["Location"] = \
            f"{base_url}/sword-app/getid/app/{sword_id}"

    return Response(content=entry,
                    status_code=200 if headers.no_op else 202,
                    media_type=ENTRY_CONTENT_TYPE,
                    headers=response_headers)


def depositor_user(depositor, endorsements) -> PublicUser:
    """The `User` recorded as the creator of a SWORD submission.

    The depositing account, not the contact author -- the contact reaches the
    submission through `SetProxyInformation`.

    ``endorsements`` comes from `collections.endorsement_wildcards`, which turns the
    depositor's group flags into the wildcards `SetPrimaryClassification` expects.
    """
    return PublicUser(user_id=str(depositor.user_id),
                      name=depositor.nickname,
                      email=depositor.email,
                      endorsements=list(endorsements))


def deposit_client(request: Request, headers) -> HttpClient:
    """The `Client` recorded for a deposit.

    ``version`` carries the depositor's ``User-Agent``, which SWORD also echoes
    back in ``<sword:userAgent>``. The address is taken from
    ``X-Forwarded-For``'s last hop when present, matching how the Flask UI reads it
    behind the load balancer (`submit_ce.ui.auth._ip_address`).
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        remote_addr = forwarded.split(",")[-1].strip()
    else:
        remote_addr = request.client.host if request.client else "unknown"
    return HttpClient(remote_addr=remote_addr, version=headers.user_agent)
