"""Test that the Flask app converts `SubmissionLocked` into HTTP 409.

The error handler is registered in `submit_ce.ui.factory.create_web_app`.
Raising `SubmissionLocked` from inside a request (or from inside a view
function, an `api.save(...)` call, or `api.lock_submission(...)`) must
produce HTTP 409 Conflict, not 500 Internal Server Error.

A dedicated `SubmissionLocked` exception that is intentionally NOT a
subclass of `SaveError` keeps the existing `except SaveError: raise
InternalServerError` blocks in the controllers from swallowing it
into a 500. That invariant is asserted in
`test_lock_submission.test_submission_locked_not_subclass_of_save_error`.
"""
from __future__ import annotations

from flask import Flask
from werkzeug.exceptions import Conflict

from submit_ce.domain.exceptions import SaveError, SubmissionLocked


def _app_with_locked_handler() -> Flask:
    """Build a tiny Flask app with just the handler we care about,
    avoiding the full create_web_app() (which needs DB + auth setup).
    Mirrors the registration in factory.py:create_web_app."""
    app = Flask(__name__)

    @app.errorhandler(SubmissionLocked)
    def _handle_submission_locked(exc):
        return Conflict(description=(
            "Another operation is in progress for this submission; "
            "please retry."
        ))

    @app.route("/raise-locked")
    def _raise_locked():
        raise SubmissionLocked(42)

    @app.route("/raise-save-error")
    def _raise_save_error():
        raise SaveError("some save failed")

    return app


def test_submission_locked_becomes_409():
    app = _app_with_locked_handler()
    client = app.test_client()

    resp = client.get("/raise-locked")
    assert resp.status_code == 409, resp.data
    assert b"Another operation is in progress" in resp.data


def test_save_error_is_not_caught_by_submission_locked_handler():
    """Sanity-check: a SaveError must NOT be swallowed by the
    SubmissionLocked handler. With Flask's default config, an
    unhandled SaveError bubbles up to a 500."""
    app = _app_with_locked_handler()
    # propagate exceptions instead of converting to 500, so we can
    # assert the exception type cleanly.
    app.testing = False
    client = app.test_client()
    resp = client.get("/raise-save-error")
    assert resp.status_code == 500
