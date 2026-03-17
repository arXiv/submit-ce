import pytest
from xprocess import ProcessStarter
import socket
import tempfile

from google.cloud import pubsub_v1


def get_unused_port():
    """Returns an unused local TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('localhost', 0))
        return s.getsockname()[1]

@pytest.fixture(scope="session")
def project_id():
    return "arxiv-submit-ce-pubsub-test"


@pytest.fixture
def port_and_tmpdir():
    port = get_unused_port()
    with tempfile.TemporaryDirectory(suffix=f"arxiv_policy_pubsub_emulator_{port}") as td:
        yield port, td

@pytest.fixture
def pubsub_emulator(monkeypatch, xprocess, project_id, port_and_tmpdir):
    port, tmpdir = port_and_tmpdir
    class Starter(ProcessStarter):
        timeout = 12
        pattern = "INFO: Server started"
        args=f"gcloud beta emulators pubsub start --project={project_id} --host-port=[::1]:{port} --data-dir={tmpdir}".split()

    pubsub_logfile = xprocess.ensure("pubsub_emulator", Starter)

    # From gcloud beta emulators pubsub env-init
    # PUBSUB_EMULATOR_HOST=localhost:8085
    monkeypatch.setenv("PUBSUB_EMULATOR_HOST", f"localhost:{port}")
    monkeypatch.setenv("PUBSUB_PROJECT_ID", project_id)

    try:
        yield pubsub_logfile
    finally:
        xprocess.getinfo("pubsub_emulator").terminate()
        print(f"pubsub_emulator logs at {pubsub_logfile}")


@pytest.fixture
def submission_topic(pubsub_emulator, project_id):
    publisher = pubsub_v1.PublisherClient(
        pubsub_v1.types.BatchSettings(
            max_messages = 1
        )
    )
    topic_name = f"projects/{project_id}/topics/fake-submission-events"
    topic = publisher.create_topic(request={"name": topic_name})
    return publisher, topic.name
