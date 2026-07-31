"""Run the submit-ce UI.

gcloud auth application-default login
gcloud beta emulators pubsub start --project=arxiv-development
uv run python local_ui.py

"""
import getpass
import os

# Removes log messages like: GET /css/style.css
import logging
logging.getLogger("werkzeug").setLevel(logging.WARNING)

# Store files in this bucket subdir. defaults to your laptop username.
DEV_NAME = None

os.environ.setdefault('COMPILE_API_IMPERSONATE_SA', 'submit-ce-dev-sa@arxiv-development.iam.gserviceaccount.com')
os.environ.setdefault('GCLOUD_PROJECT', 'arxiv-development')
os.environ.setdefault('LOCAL_LOGIN', '1')
os.environ.setdefault('PUBSUB_EMULATOR_HOST', 'localhost:8085')
os.environ.setdefault('LOCAL_LOGIN', 'True')
os.environ.setdefault('QA_PUBSUB_ENABLED', 'False')
os.environ.setdefault('QA_GS_BUCKET', 'arxiv-submit-dev')
os.environ.setdefault('QA_GS_PREFIX', DEV_NAME or getpass.getuser())
os.environ.setdefault('STORE', 'gs')
os.environ.setdefault('STORE_GS_BUCKET', 'arxiv-submit-dev')
os.environ.setdefault('STORE_GS_PREFIX', DEV_NAME or getpass.getuser())
os.environ.setdefault('TEMPLATES_AUTO_RELOAD', '1')

from submit_ce.ui.factory import create_web_app

def ensure_pubsub_topic():
    """Create the QA metadata topic on the localhost emulator."""
    from submit_ce.ui.config import settings
    from google.cloud import pubsub_v1
    if not settings.QA_PUBSUB_ENABLED:
        return
    emulator = os.environ.get('PUBSUB_EMULATOR_HOST')
    try:
        pubsub_v1.PublisherClient().create_topic(
            request={'name': settings.QA_PUBSUB_TOPIC})
        print(f"INFO: created Pub/Sub topic {settings.QA_PUBSUB_TOPIC} on emulator {emulator}")
    except Exception as ex:  # AlreadyExists, or emulator not running
        print(f"INFO: Pub/Sub topic {settings.QA_PUBSUB_TOPIC} on emulator {emulator} "
              f"({type(ex).__name__})")


if __name__ == '__main__':
    user_prefix = os.environ['STORE_GS_PREFIX']
    print(f"INFO: Using GCS bucket gs://arxiv-submit-dev/{user_prefix}/")
    print(f"INFO: GCP project: {os.environ['GCLOUD_PROJECT']}")
    print(f"INFO: Pub/Sub emulator: {os.environ['PUBSUB_EMULATOR_HOST']}")
    print(f"INFO: Local logins enabled?: {os.environ['LOCAL_LOGIN']}")
    ensure_pubsub_topic()

    app = create_web_app()
    app.run(debug=True, port=8000)
