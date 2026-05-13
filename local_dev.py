"""Run the submit-ce UI against real GCS for local development.

Uses bucket `arxiv-submit-dev` in project `arxiv-development`, with a
per-developer prefix derived from `$USER` so developers don't collide.

Run as:
    uv run python local_dev.py

Requires `gcloud auth application-default login` (or equivalent ADC setup).
"""
import getpass
import os

os.environ.setdefault('STORE', 'gs')
os.environ.setdefault('STORE_GS_BUCKET', 'arxiv-submit-dev')
os.environ.setdefault('STORE_GS_PREFIX', getpass.getuser())
os.environ.setdefault('GCLOUD_PROJECT', 'arxiv-development')
os.environ.setdefault('TEMPLATES_AUTO_RELOAD', '1')

from submit_ce.ui.factory import create_web_app

if __name__ == '__main__':
    user_prefix = os.environ['STORE_GS_PREFIX']
    print(f"INFO: Using GCS bucket gs://arxiv-submit-dev/{user_prefix}/")
    print(f"INFO: GCP project: {os.environ['GCLOUD_PROJECT']}")

    app = create_web_app()
    app.run(debug=True, port=8000)
