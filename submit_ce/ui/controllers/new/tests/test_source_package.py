"""Tests for :mod:`submit_ce.ui.controllers.new.source_package`.

Focus: the Download Source Package build must run inside the submission's
critical section (bdc34's review point on PR #76). We verify that the
controller dispatches a ``BuildSourcePackage`` event -- which builds the tar
under SubmitApi.save's row lock -- and streams the archive that was persisted
under that lock, rather than building outside any lock.
"""

from http import HTTPStatus as status

from werkzeug.datastructures import MultiDict
from flask import current_app

from arxiv.files import FileDoesNotExist

from submit_ce.domain.event.process import BuildSourcePackage
from submit_ce.implementations.file_store.mock_file_store import MockFileStore
from submit_ce.ui.controllers.new.source_package import download_source_package


def test_download_builds_package_under_lock(
        app, authorized_user, authorized_user_session, sub_primary):
    """Downloading builds via BuildSourcePackage (under the lock) and streams
    the archive persisted by that event."""
    session, _ = authorized_user_session
    with app.app_context():
        sid = str(sub_primary.submission_id)

        store = MockFileStore()
        current_app.api.store = store
        store._source[sid] = {"main.tex": b"\\documentclass{article}\n"}

        stream, code, headers = download_source_package(
            "GET", MultiDict(), session, sid)

        assert code == status.OK
        assert headers["Content-Type"] == "application/gzip"
        # Valid gzip magic bytes.
        data = stream.read()
        assert data[:2] == b"\x1f\x8b"

        # The archive was persisted under the lock and is readable back.
        assert not isinstance(store.get_source_package(sid), FileDoesNotExist)

        # The build went through SubmitApi.save (the critical section): a
        # BuildSourcePackage event is now in the submission history. Reload
        # via get_with_history to bypass the per-request `g` cache.
        _, events = current_app.api.get_with_history(sid)
        assert any(isinstance(e, BuildSourcePackage) for e in events)


def test_download_no_files_returns_not_found(
        app, authorized_user, authorized_user_session, sub_primary):
    """With no uploaded source files, the download 404s before building."""
    from werkzeug.exceptions import NotFound
    import pytest

    session, _ = authorized_user_session
    with app.app_context():
        sid = str(sub_primary.submission_id)
        current_app.api.store = MockFileStore()  # empty workspace

        with pytest.raises(NotFound):
            download_source_package("GET", MultiDict(), session, sid)
