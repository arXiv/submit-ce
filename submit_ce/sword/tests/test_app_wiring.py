"""Store selection for the app.

`build_deposit_store` picks the production backend from settings. A mistake here
would be quiet and bad -- a deployment that thinks it is on GCS but is really
using the in-memory store loses every deposit on restart -- so every branch is
asserted, including the refusal to guess.
"""

from types import SimpleNamespace

import pytest

from submit_ce.sword.app import DEPOSIT_PREFIX, build_deposit_store
from submit_ce.sword.deposits import InMemoryDepositStore
from submit_ce.sword.gs_deposits import GsDepositStore


def _settings(**overrides):
    base = dict(STORE="null", STORE_GS_BUCKET="arxiv-submit-dev",
                STORE_GS_PREFIX="")
    base.update(overrides)
    return SimpleNamespace(**base)


def test_null_store_selects_the_in_memory_backend():
    store = build_deposit_store(_settings(STORE="null"))
    assert isinstance(store, InMemoryDepositStore)


def test_an_unknown_store_raises_rather_than_using_memory():
    """The guard that keeps a future backend from silently landing in memory.

    ``Settings.STORE`` is a ``Literal["gs", "null"]``, so pydantic rejects a typo
    before this is reached -- but adding a third value to that Literal without
    adding it here would otherwise route SWORD deposits to the heap while the file
    store went to the real backend.
    """
    with pytest.raises(NotImplementedError, match="s3"):
        build_deposit_store(_settings(STORE="s3"))


class _StubClient:
    """Enough of ``storage.Client`` for the constructor; no credentials needed."""

    def bucket(self, name):
        return SimpleNamespace(name=name)


def test_gs_store_selects_the_bucket_backend(monkeypatch):
    """Client construction is stubbed: a real one would need credentials."""
    monkeypatch.setattr("google.cloud.storage.Client", _StubClient)

    store = build_deposit_store(_settings(STORE="gs"))
    assert isinstance(store, GsDepositStore)
    assert store.gs_bucket == "arxiv-submit-dev"
    assert store.gs_prefix == DEPOSIT_PREFIX


def test_gs_prefix_nests_under_the_per_developer_prefix(monkeypatch):
    """local_sword.py sets STORE_GS_PREFIX to the developer's username."""
    monkeypatch.setattr("google.cloud.storage.Client", _StubClient)

    store = build_deposit_store(_settings(STORE="gs", STORE_GS_PREFIX="bgm37"))
    assert store.gs_prefix == f"bgm37/{DEPOSIT_PREFIX}"


def test_app_exposes_a_deposit_store(sword_app):
    """The app under test runs with STORE=null, pinned by the root conftest."""
    assert isinstance(sword_app.state.deposits, InMemoryDepositStore)


# ------------------------------------------------------------------ deposit client


def test_deposit_client_uses_the_forwarded_address():
    """Behind the load balancer the real address is the last X-Forwarded-For hop.

    Mirrors how the Flask UI reads it (`submit_ce.ui.auth._ip_address`).
    """
    from submit_ce.sword.app import deposit_client

    request = SimpleNamespace(
        headers={"X-Forwarded-For": "203.0.113.7, 10.0.0.1"},
        client=SimpleNamespace(host="10.0.0.1"))
    client = deposit_client(request, SimpleNamespace(user_agent="demo/1.1"))

    assert client.remote_addr == "10.0.0.1"
    assert client.version == "demo/1.1"


def test_deposit_client_falls_back_to_the_socket_address():
    from submit_ce.sword.app import deposit_client

    request = SimpleNamespace(headers={},
                              client=SimpleNamespace(host="198.51.100.4"))
    client = deposit_client(request, SimpleNamespace(user_agent=None))
    assert client.remote_addr == "198.51.100.4"
    assert client.version is None


def test_deposit_client_without_a_peer():
    """Starlette leaves ``client`` unset for some transports."""
    from submit_ce.sword.app import deposit_client

    request = SimpleNamespace(headers={}, client=None)
    assert deposit_client(request, SimpleNamespace(user_agent=None)).remote_addr \
        == "unknown"


# ------------------------------------------------------------------- self-links


def _fake_request(headers, scheme="http", netloc="127.0.0.1:8001"):
    return SimpleNamespace(headers=headers,
                           url=SimpleNamespace(scheme=scheme, netloc=netloc))


def test_base_url_from_the_request_itself():
    """Local dev: no proxy headers, so the socket's own scheme and host win."""
    from submit_ce.sword.app import request_base_url

    request = _fake_request({"Host": "localhost:8001"})
    assert request_base_url(request) == "http://localhost:8001"


def test_base_url_honours_forwarded_proto():
    """Cloud Run terminates TLS, so the container only ever sees http."""
    from submit_ce.sword.app import request_base_url

    request = _fake_request({"Host": "arxiv.org", "X-Forwarded-Proto": "https"})
    assert request_base_url(request) == "https://arxiv.org"


def test_base_url_honours_forwarded_host():
    from submit_ce.sword.app import request_base_url

    request = _fake_request({"Host": "sword-ce-dev.run.app",
                             "X-Forwarded-Proto": "https",
                             "X-Forwarded-Host": "dev.arxiv.org"})
    assert request_base_url(request) == "https://dev.arxiv.org"


def test_base_url_takes_the_first_hop_of_a_forwarded_list():
    """Chained proxies append, so the client-facing value comes first."""
    from submit_ce.sword.app import request_base_url

    request = _fake_request({"Host": "internal",
                             "X-Forwarded-Proto": "https, http",
                             "X-Forwarded-Host": "export.arxiv.org, internal"})
    assert request_base_url(request) == "https://export.arxiv.org"


def test_base_url_falls_back_to_the_url_netloc():
    """No Host header at all, which happens on raw HTTP/1.0 requests."""
    from submit_ce.sword.app import request_base_url

    request = _fake_request({}, netloc="127.0.0.1:8001")
    assert request_base_url(request) == "http://127.0.0.1:8001"


def test_served_links_follow_the_request_host(sword_app, depositor):
    """End to end: a deposit made via localhost is told about localhost."""
    from fastapi.testclient import TestClient

    from submit_ce.sword.tests.client import basic_auth, edit_media_link

    local = TestClient(sword_app, base_url="http://localhost:8001")
    response = local.post(
        "/sword-app/cs-collection", content=b"PK\x03\x04zip",
        headers={"Authorization": basic_auth(depositor.nickname,
                                             depositor.password),
                 "Content-Type": "application/zip"})
    assert response.status_code == 201, response.text
    assert edit_media_link(response.content).startswith(
        "http://localhost:8001/sword-app/edit/")
    assert response.headers["Location"].startswith(
        "http://localhost:8001/sword-app/getid/app/")


# ------------------------------------------------------------- interactive docs

DOC_PATHS = ["/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"]


def _paths(app):
    return {route.path for route in app.routes}


def test_docs_are_absent_by_default(client):
    """404, not 401: the routes must not exist at all.

    Legacy exposed nothing under the SWORD app without Basic auth (``sword.conf``
    gated /sword-app at the Apache layer), and a 401 would still advertise that a
    schema is there to be had.
    """
    for path in DOC_PATHS:
        assert client.get(path).status_code == 404, path


def test_the_schema_route_is_gone_too(sword_app):
    """The HTML pages are the visible half; ``/openapi.json`` is the useful half."""
    assert "/openapi.json" not in _paths(sword_app)
    assert sword_app.openapi_url is None


def test_docs_appear_under_local_login(monkeypatch, sword_db):
    """A developer running local_sword.py still gets them."""
    from submit_ce.sword.app import create_sword_app
    from submit_ce.ui.config import settings as sce_settings

    monkeypatch.setattr(sce_settings, "LOCAL_LOGIN", True)
    app = create_sword_app()

    assert "/docs" in _paths(app)
    assert "/redoc" in _paths(app)
    assert app.openapi_url == "/openapi.json"


def test_the_protocol_routes_do_not_depend_on_the_flag(sword_app):
    """Dropping the docs must not drop anything a depositor uses."""
    paths = _paths(sword_app)
    assert "/status" in paths
    assert "/sword-app/servicedocument" in paths
    assert "/sword-app/{collection}-collection" in paths
    assert "/resolve/app/{sword_id}" in paths


def test_status_stays_public(client):
    """It is the health check, so it must answer without credentials."""
    assert client.get("/status").status_code == 200
