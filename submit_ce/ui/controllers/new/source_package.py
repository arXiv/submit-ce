"""Controller for the Download Source Package endpoint.

Serves a freshly-built ``.tar.gz`` of the current source files. The
actual tar-building lives on the file store
(``SubmissionFileStore.build_source_package``) so the same builder is
shared with other callers that need a current-source archive (notably
``CompileApiService.start_preflight``, which rebuilds the persisted
``<submission_id>.tar.gz`` before each preflight call so tex2pdf
never receives a stale snapshot).

Mirrors the pattern used by the Submit 1.5 ``create_source_package``
Perl routine in ``Submit.pm``: the canonical source is the individual
files under ``<submission_id>/src/``, and the archive is built at
request time rather than maintained as a separate persistent artifact.

Note: We deliberately do *not* serve the persisted ``<submission_id>.tar.gz``
in the bucket directly: that copy is refreshed by
``compile_at_gcp.py`` on a successful compile (see the
``shutil.copy2(temp_tar_path, new_tar_path)`` block guarded by
``not preflight and status == 'success'``) and by
``start_preflight``. For a Download Package button shown on the
pre-compile Upload Files and Review Files steps, building from current
source via the file store is the correct semantics, and never reading
the persisted ``<submission_id>.tar.gz`` is the simplest way to be
sure we don't serve a stale snapshot.

Note: A warning is logged inside the file store when a file is listed
in the workspace but cannot be read back from the bucket. We may want
to improve handling for such an error by alerting the user visually
in the UI and systematically detecting such drift; it may indicate
inconsistent bucket access.

Linked from the sidebar of the Upload Files and Review Files pages.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from http import HTTPStatus as status
from typing import Any, Dict, Tuple

from arxiv.auth.domain import Session
from arxiv.files import FileDoesNotExist
from flask import current_app
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import NotFound

from submit_ce.domain.event.process import BuildSourcePackage
from submit_ce.ui.backend import get_submission

from ...auth import user_and_client_from_session


logger = logging.getLogger(__name__)


def download_source_package(
    method: str,
    params: MultiDict,
    session: Session,
    submission_id: str,
    **kwargs: Any,
) -> Tuple[io.BytesIO, int, Dict[str, str]]:
    """Return the submission's current source as a freshly-built .tar.gz.

    The filename follows the Submit 1.5 convention:
    ``submission_<id>-<YYYYMMDD-HHMM>.tar.gz``.
    """
    # Verify the submission exists in the current user's scope. Auth is
    # already enforced by the route's @scoped decorator.
    submission, _ = get_submission(submission_id)

    file_store = current_app.api.get_file_store()
    workspace = file_store.get_workspace(submission_id=submission_id)
    if not workspace or not workspace.files:
        raise NotFound(
            "No source files are attached to this submission yet. "
            "Upload files on the Upload Files step before downloading "
            "a source package."
        )

    # Build the archive inside the submission's critical section. Dispatching
    # BuildSourcePackage makes SubmitApi.save hold the submission row lock
    # while write_source_package assembles the tar, so a concurrent upload or
    # delete cannot change the file set mid-build (bdc34's review point on
    # PR #76). We then stream the archive that was just persisted under the
    # lock, rather than calling the unlocked build_source_package directly.
    submitter, client = user_and_client_from_session(session)
    current_app.api.save(
        BuildSourcePackage(creator=submitter, client=client),
        submission_id=submission_id,
    )
    package = file_store.get_source_package(submission_id)
    if isinstance(package, FileDoesNotExist):
        logger.error(
            "source_package: package missing after BuildSourcePackage for %s",
            submission_id,
        )
        raise NotFound(
            "The source package could not be built. Please try again; if the "
            "problem persists, contact arXiv support."
        )
    stream = io.BytesIO(package.download_as_bytes())
    stream.seek(0)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    filename = f"submission_{submission_id}-{timestamp}.tar.gz"
    headers = {
        "Content-Type": "application/gzip",
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
    }
    return stream, status.OK, headers
