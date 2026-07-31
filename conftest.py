"""Repo-wide test guards against production side effects.

Two layers, because settings alone are not enough:

1. **Pinned settings.** `submit_ce.ui.config.settings` is a module-level
   singleton read at call time, and it is populated from the environment
   (pydantic-settings). So an exported ``EMAIL_MODE=HALON`` would otherwise
   make the ``app`` fixture build a real Halon SMTP service, and UI tests do
   trigger sends. The same applies to ``QA_PUBSUB_ENABLED``, which defaults to
   ``True``.

2. **A socket guard.** ``COMPILE_API_URL`` defaults to a live Cloud Run URL and
   is not pinned by any test; today every compile-path test swaps in
   `MockCompileMimesisPdf` by hand, which is opt-in and easy to forget. The
   guard turns "no test happens to reach out" into "no test can", and reports
   the address it blocked instead of hanging on a retry loop.

A test that genuinely needs the network can opt out::

    @pytest.mark.allow_network
    def test_talks_to_a_real_service():
        ...

Loopback is always allowed, so sqlite, the Pub/Sub emulator and any local
service still work.
"""

import socket

import pytest

from submit_ce.ui.config import settings

_REAL_CONNECT = socket.socket.connect
_REAL_CONNECT_EX = socket.socket.connect_ex

_LOOPBACK = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}

# Flipped per-test by the _network_guard fixture below.
_allow_network = False


def _is_local(address) -> bool:
    """True for loopback and for non-IP addresses (AF_UNIX and friends)."""
    if not isinstance(address, tuple) or not address:
        return True
    host = str(address[0])
    return (host in _LOOPBACK
            or host.startswith("127.")
            or host.startswith("::ffff:127."))


def _blocked(address) -> bool:
    return not _allow_network and not _is_local(address)


def _guarded_connect(self, address):
    if _blocked(address):
        raise OSError(
            f"Blocked outbound connection to {address!r} during tests. "
            "Mock the service, or mark the test @pytest.mark.allow_network."
        )
    return _REAL_CONNECT(self, address)


def _guarded_connect_ex(self, address):
    if _blocked(address):
        raise OSError(
            f"Blocked outbound connection to {address!r} during tests. "
            "Mock the service, or mark the test @pytest.mark.allow_network."
        )
    return _REAL_CONNECT_EX(self, address)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "allow_network: permit outbound network connections in this test.")
    socket.socket.connect = _guarded_connect
    socket.socket.connect_ex = _guarded_connect_ex


def pytest_unconfigure(config):
    socket.socket.connect = _REAL_CONNECT
    socket.socket.connect_ex = _REAL_CONNECT_EX


@pytest.fixture(autouse=True)
def _network_guard(request):
    """Honour the ``allow_network`` marker for the duration of one test."""
    global _allow_network
    previous = _allow_network
    _allow_network = request.node.get_closest_marker("allow_network") is not None
    try:
        yield
    finally:
        _allow_network = previous


@pytest.fixture(autouse=True, scope="session")
def _no_production_side_effects():
    """Pin the settings that would otherwise reach real services."""
    settings.EMAIL_MODE = "TESTING"          # -> EmailInMemory, never SMTP
    settings.QA_PUBSUB_ENABLED = False       # default is True
    settings.STORE = "null"                  # -> NullFileStore, never GCS
    settings.COMPILE_API_URL = "http://localhost:0"  # http:// also skips ID tokens
    yield
