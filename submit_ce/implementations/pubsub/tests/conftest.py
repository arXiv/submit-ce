import re
import shutil
import socket

import pytest
from xprocess import ProcessStarter

from google.cloud import pubsub_v1


@pytest.fixture(scope="session")
def project_id():
    return "arxiv-submit-ce-pubsub-test"


@pytest.fixture(scope="session")
def emulator_port():
    """An unused local TCP port, chosen once for the whole session.

    Binding a port to learn it is free and then letting another process bind it
    is a race; doing this once per session rather than once per test shrinks the
    window to a single occurrence.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def pubsub_emulator(xprocess, project_id, emulator_port, tmp_path_factory):
    """A local Pub/Sub emulator, started once for the whole session.

    Skipped rather than failed when the emulator cannot be run, so a checkout
    without the gcloud SDK (or without its ``pubsub-emulator`` component) does
    not report errors for an optional dependency. CI skips this directory
    outright with ``--ignore``; see .github/workflows/python-app.yml.
    """
    if shutil.which("gcloud") is None:
        pytest.skip("gcloud is not installed, so the Pub/Sub emulator cannot be started")

    data_dir = tmp_path_factory.mktemp("pubsub-emulator-data")

    class Starter(ProcessStarter):
        timeout = 60
        pattern = "INFO: Server started"
        # Bind the same address the client will dial. Binding ``[::1]`` while
        # advertising ``PUBSUB_EMULATOR_HOST=localhost`` leaves it to the
        # client's name resolution whether the connection lands, and a miss
        # surfaces as a gRPC UNAVAILABLE retry loop rather than a clear error.
        args = (f"gcloud beta emulators pubsub start --project={project_id}"
                f" --host-port=localhost:{emulator_port}"
                f" --data-dir={data_dir}").split()

    try:
        pubsub_logfile = xprocess.ensure("pubsub_emulator", Starter)
    except Exception as exc:  # component missing, startup timeout, port taken
        pytest.skip(f"could not start the Pub/Sub emulator: {exc}")

    with pytest.MonkeyPatch.context() as monkeypatch:
        # From `gcloud beta emulators pubsub env-init`. Setting this also makes
        # the client use anonymous credentials, so it cannot reach real GCP.
        monkeypatch.setenv("PUBSUB_EMULATOR_HOST", f"localhost:{emulator_port}")
        monkeypatch.setenv("PUBSUB_PROJECT_ID", project_id)
        try:
            yield pubsub_logfile
        finally:
            xprocess.getinfo("pubsub_emulator").terminate()
            print(f"pubsub_emulator logs at {pubsub_logfile}")


@pytest.fixture
def unique_suffix(request):
    """A per-test suffix for Pub/Sub resource names.

    The emulator is session-scoped, so topics and subscriptions created by one
    test are still there for the next one; a fixed name reused across tests
    would fail with AlreadyExists.
    """
    return re.sub(r"[^0-9a-zA-Z-]", "-", request.node.name)


@pytest.fixture
def submission_topic(pubsub_emulator, project_id, unique_suffix):
    """A publisher plus a topic unique to the calling test."""
    publisher = pubsub_v1.PublisherClient(
        pubsub_v1.types.BatchSettings(
            max_messages = 1
        )
    )
    topic_name = f"projects/{project_id}/topics/submission-events-{unique_suffix}"
    topic = publisher.create_topic(request={"name": topic_name})
    return publisher, topic.name
