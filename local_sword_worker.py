"""Run the SWORD background worker.

    gcloud auth application-default login
    uv run python local_sword_worker.py

It polls for SWORD deposits that have been created but not yet finished -- runs
preflight, records the source format, compiles, and finalizes -- so a deposit made
through `local_sword.py` ends up ``submitted`` instead of sitting at ``incomplete``.
Watch one go through with::

    curl -s localhost:8001/resolve/app/<sword_id>

Env vars match `local_sword.py` exactly, so both point at the same dev database and
the same GCS prefix. Run them side by side in two shells: the API accepts deposits,
this finishes them.

    --once              one pass, then exit (default is to keep polling)
    --interval N        seconds between passes (default 60)
    --limit N           process at most N submissions per pass

**This is deliberately a separate process.** The SWORD API and the Flask UI both
scale to many instances, and neither starts a worker -- if they did, every instance
would run one, and they would fight over the same submissions. There is no lease,
so one worker is the supported deployment; see `submit_ce.sword.worker_loop`.

It really does compile
----------------------
Unlike `local_sword.py`, which only accepts deposits, this calls tex2pdf for real
and can take minutes per submission. It also finalizes, and `FinalizeSubmission`
sends mail to the submitter and to the archive's moderators -- so point it at a dev
database, and check ``EMAIL_MODE`` before running it against anything shared.
"""
import argparse
import getpass
import logging
import os

# Store files in this bucket subdir. Defaults to your laptop username.
DEV_NAME = None

os.environ.setdefault('COMPILE_API_IMPERSONATE_SA', 'submit-ce-dev-sa@arxiv-development.iam.gserviceaccount.com')
os.environ.setdefault('GCLOUD_PROJECT', 'arxiv-development')
os.environ.setdefault('QA_PUBSUB_ENABLED', 'False')
os.environ.setdefault('QA_GS_BUCKET', 'arxiv-submit-dev')
os.environ.setdefault('QA_GS_PREFIX', DEV_NAME or getpass.getuser())
os.environ.setdefault('STORE', 'gs')
os.environ.setdefault('STORE_GS_BUCKET', 'arxiv-submit-dev')
os.environ.setdefault('STORE_GS_PREFIX', DEV_NAME or getpass.getuser())
# Nothing here serves HTTP, so LOCAL_LOGIN is deliberately not set: it only gates
# the API's /docs pages and the UI's /debug/login.

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(name)s: %(message)s')

# Imported after the environment is set above: submit_ce.ui.config builds its
# `settings` singleton at import time, so importing earlier would bake in the
# production-ish defaults instead of these dev ones.
from submit_ce.sword.worker_loop import (  # noqa: E402
    DEFAULT_INTERVAL,
    configure_database,
    run_once,
)


def _parse(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--once', action='store_true',
                        help='one pass, then exit')
    parser.add_argument('--interval', type=int, default=DEFAULT_INTERVAL,
                        help=f'seconds between passes (default {DEFAULT_INTERVAL})')
    parser.add_argument('--limit', type=int, default=None,
                        help='process at most this many submissions per pass')
    return parser.parse_args(argv)


if __name__ == '__main__':
    import time

    from arxiv.db import Session
    from submit_ce.implementations.legacy_implementation.fastapi_impl import (
        FastapiSubmitImplementation,
        remove_session,
    )
    from submit_ce.implementations.wiring import config_backend_api
    from submit_ce.ui.config import settings

    args = _parse()

    user_prefix = os.environ['STORE_GS_PREFIX']
    print(f"INFO: Using GCS bucket gs://{os.environ['STORE_GS_BUCKET']}/{user_prefix}/")
    print(f"INFO: GCP project: {os.environ['GCLOUD_PROJECT']}")
    print(f"INFO: EMAIL_MODE={settings.EMAIL_MODE} "
          "(finalizing emails the submitter and moderators)")

    # Before anything queries: arxiv.db binds per model, and the wiring below only
    # sets the default bind. See worker_loop.configure_database.
    configure_database()
    api = config_backend_api(settings, impl=FastapiSubmitImplementation)

    # Same startup check as local_sword.py, and it matters more here: this process
    # actually calls the compile service, so a bad config should surface now rather
    # than fourteen minutes into a timeout.
    try:
        healthy, message = api.healthy()
    finally:
        remove_session()
    print(f"{'INFO' if healthy else 'ERROR'}: backend: {message}")

    if args.once:
        print("INFO: single pass")
        run_once(api, Session, args.limit)
        remove_session()
        raise SystemExit(0)

    print(f"INFO: polling every {args.interval}s -- Ctrl-C to stop")
    try:
        while True:
            try:
                run_once(api, Session, args.limit)
            except Exception:
                logging.exception("pass failed; continuing")
            finally:
                # Do not hold a database connection across the sleep.
                remove_session()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nINFO: stopped")
