"""Run the submit-ce submission mutation API (SUBMISSION-257).

    gcloud auth application-default login
    uv run python local_api.py

Then, in another shell:

    curl -si localhost:8002/status

Runs on 8002 so it can sit alongside local_ui.py (8000) and local_sword.py
(8001); all talk to the same dev database and GCS prefix.

For auto-reload while iterating:

    uv run uvicorn submit_ce.fastapi.app:create_api_app --factory --reload --port 8002
"""
import getpass
import logging
import os

DEV_NAME = None
PORT = 8002

os.environ.setdefault('COMPILE_API_IMPERSONATE_SA', 'submit-ce-dev-sa@arxiv-development.iam.gserviceaccount.com')
os.environ.setdefault('GCLOUD_PROJECT', 'arxiv-development')
os.environ.setdefault('QA_PUBSUB_ENABLED', 'False')
os.environ.setdefault('QA_GS_BUCKET', 'arxiv-submit-dev')
os.environ.setdefault('QA_GS_PREFIX', DEV_NAME or getpass.getuser())
os.environ.setdefault('STORE', 'gs')
os.environ.setdefault('STORE_GS_BUCKET', 'arxiv-submit-dev')
os.environ.setdefault('STORE_GS_PREFIX', DEV_NAME or getpass.getuser())
os.environ.setdefault('LOCAL_LOGIN', '1')

logging.basicConfig(level=logging.INFO)

from submit_ce.fastapi.app import create_api_app  # noqa: E402


if __name__ == '__main__':
    import uvicorn
    from submit_ce.implementations.legacy_implementation.fastapi_impl import (
        remove_session,
    )

    print(f"INFO: Using GCS bucket gs://{os.environ['STORE_GS_BUCKET']}/{os.environ['STORE_GS_PREFIX']}/")
    app = create_api_app()
    try:
        healthy, message = app.state.api.healthy()
    finally:
        remove_session()
    print(f"{'INFO' if healthy else 'ERROR'}: backend: {message}")
    print(f"INFO: submission mutation API on http://127.0.0.1:{PORT} -- try /status")
    uvicorn.run(app, host='127.0.0.1', port=PORT)
