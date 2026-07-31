"""The repo-root test guards must actually hold.

If any of these fail, the rest of the suite can reach real services. See the
root ``conftest.py`` for what is being guarded and why.
"""

import socket

import pytest

from submit_ce.ui.config import settings

# RFC 5737 TEST-NET-1: reserved for documentation, never routed, and an IP
# literal so nothing has to be resolved before the guard rejects it.
UNROUTABLE = ("192.0.2.1", 80)


def test_settings_are_pinned_away_from_real_services():
    assert settings.EMAIL_MODE == "TESTING", "would build a real SMTP service"
    assert settings.QA_PUBSUB_ENABLED is False, "would publish to Pub/Sub"
    assert settings.STORE == "null", "would read and write real GCS buckets"
    assert not settings.COMPILE_API_URL.startswith("https://"), \
        "an https:// compile URL also triggers real GCP ID-token minting"


def test_outbound_connection_is_blocked():
    """A non-local connect raises before any traffic leaves the process."""
    with pytest.raises(OSError, match="Blocked outbound connection"):
        socket.create_connection(UNROUTABLE, timeout=1)


def test_loopback_is_still_allowed():
    """sqlite, the Pub/Sub emulator and other local services must keep working."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass  # connected; the guard did not interfere


def test_guard_is_active_by_default():
    import conftest
    assert conftest._allow_network is False


@pytest.mark.allow_network
def test_allow_network_marker_lifts_the_guard():
    import conftest
    assert conftest._allow_network is True
