"""Run the submit-ce SWORD API.

gcloud auth application-default login
uv run python local_sword.py

Then, in another shell:

    curl -si localhost:8001/status

Runs on 8001 so it can sit alongside `local_ui.py` on 8000; both talk to the
same dev database and GCS prefix, so a deposit made here shows up in the UI.

For auto-reload while iterating, run uvicorn directly instead -- the env vars
below are inherited by the reloader's child process:

    uv run uvicorn submit_ce.sword.app:create_sword_app \
        --factory --reload --port 8001

"""
import getpass
import logging
import os

# Store files in this bucket subdir. Defaults to your laptop username.
DEV_NAME = None

PORT = 8001

os.environ.setdefault('COMPILE_API_IMPERSONATE_SA', 'submit-ce-dev-sa@arxiv-development.iam.gserviceaccount.com')
os.environ.setdefault('GCLOUD_PROJECT', 'arxiv-development')
os.environ.setdefault('QA_PUBSUB_ENABLED', 'False')
os.environ.setdefault('QA_GS_BUCKET', 'arxiv-submit-dev')
os.environ.setdefault('QA_GS_PREFIX', DEV_NAME or getpass.getuser())
os.environ.setdefault('STORE', 'gs')
os.environ.setdefault('STORE_GS_BUCKET', 'arxiv-submit-dev')
os.environ.setdefault('STORE_GS_PREFIX', DEV_NAME or getpass.getuser())
# Serves /docs, /redoc and /openapi.json, which create_sword_app() omits entirely
# unless this is set. SWORD authenticates with HTTP Basic and has no /debug/login,
# so on this app the flag does nothing else.
os.environ.setdefault('LOCAL_LOGIN', '1')

logging.basicConfig(level=logging.INFO)

# Imported after the environment is set above: submit_ce.ui.config builds its
# `settings` singleton at import time, so importing earlier would bake in the
# production-ish defaults instead of these dev ones.
from submit_ce.sword.app import create_sword_app  # noqa: E402


if __name__ == '__main__':
    import uvicorn
    from submit_ce.implementations.legacy_implementation.fastapi_impl import (
        remove_session,
    )

    user_prefix = os.environ['STORE_GS_PREFIX']
    print(f"INFO: Using GCS bucket gs://{os.environ['STORE_GS_BUCKET']}/{user_prefix}/")
    print(f"INFO: GCP project: {os.environ['GCLOUD_PROJECT']}")

    app = create_sword_app()

    # One real backend check at startup, so a misconfigured DB, file store or
    # compile service shows up here instead of on the first deposit. Runs on
    # this thread, so the session it opens is released on this thread too.
    #
    # Expect "Compiler unhealthy" even when tex2pdf is fine: is_available() in
    # CompileApiService GETs COMPILE_API_URL without the auth header every other
    # method in that class sends, so an auth-requiring Cloud Run service answers
    # 403. The DB and file store lines are trustworthy.
    try:
        healthy, message = app.state.api.healthy()
    finally:
        remove_session()
    print(f"{'INFO' if healthy else 'ERROR'}: backend: {message}")

    print(f"INFO: SWORD API on http://127.0.0.1:{PORT} -- try /status")
    print(f"INFO: Interactive docs at http://127.0.0.1:{PORT}/docs "
          "(local only; omitted when LOCAL_LOGIN is off)")
    uvicorn.run(app, host='127.0.0.1', port=PORT)
