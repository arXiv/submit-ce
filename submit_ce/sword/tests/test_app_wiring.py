"""Store selection for the app.

`build_deposit_store` picks the production backend from settings. A mistake here
would be quiet and bad -- a deployment that thinks it is on GCS but is really
using the in-memory store loses every deposit on restart -- so both branches are
asserted.
"""

from types import SimpleNamespace

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
