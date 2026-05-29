"""Controller for the Download Source Package endpoint.

Builds a fresh ``.tar.gz`` on the fly from the current source files in
the file store. Mirrors the pattern used by ``compile_at_gcp.py`` when it
bundles source for the tex2pdf service, and the Submit 1.5
``create_source_package`` Perl routine in ``Submit.pm``: in both systems
the canonical source is the individual files under
``<submission_id>/src/``, and the archive is built at request time
rather than maintained as a separate artifact.

Note: We deliberately do *not* serve the persisted ``<submission_id>.tar.gz``
in the bucket: that copy is only refreshed by ``compile_at_gcp.py`` on a
successful compile (see the ``shutil.copy2(temp_tar_path, new_tar_path)``
block guarded by ``not preflight and status == 'success'``). It
represents "the source that produced the last published PDF", not the
user's current working source. For a Download Package button shown on
the pre-compile Upload Files and Review Files steps, building from
current source is the correct semantics.

Note: A warning is logged when a file is not found in the Google Storage bucket.
We may want to improve handling for such an error by alerting the user visually
in the UI and systematically detecting and alerting on such an error. This may
indicate inconsistent access to files in the Google Storage bucket.

Linked from the sidebar of the Upload Files and Review Files pages.
"""

from __future__ import annotations

import io
import logging
import tarfile
from datetime import datetime, timezone
from http import HTTPStatus as status
from typing import Any, Dict, Tuple

from arxiv.auth.domain import Session
from flask import current_app
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import NotFound

from arxiv.files import FileDoesNotExist
from submit_ce.ui.backend import get_submission


logger = logging.getLogger(__name__)


def _build_source_tarball(submission_id: str) -> bytes:
    """Build a fresh .tar.gz from the current source files in the bucket.

    Returns the gzipped tarball bytes. Files that are listed in the
    workspace but no longer exist in the bucket (which would indicate
    file-store drift) are skipped with a warning rather than aborting
    the build.

    Raises
    ------
    werkzeug.exceptions.NotFound
        If the workspace has no source files (so there's nothing to
        package).
    """
    file_store = current_app.api.get_file_store()
    workspace = file_store.get_workspace(submission_id=submission_id)
    if not workspace or not workspace.files:
        raise NotFound(
            "No source files are attached to this submission yet. "
            "Upload files on the Upload Files step before downloading "
            "a source package."
        )

    buf = io.BytesIO()
    files_added = 0
    files_skipped = 0
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        for f in workspace.files:
            blob = file_store.get_source_file(
                submission_id=submission_id, path=f.path)
            if isinstance(blob, FileDoesNotExist):
                logger.warning(
                    "source_package: workspace lists %s but blob is missing "
                    "for submission %s; skipping",
                    f.path, submission_id,
                )
                files_skipped += 1
                continue
            try:
                data = blob.download_as_bytes()
            except Exception as exc:
                logger.warning(
                    "source_package: could not read %s for submission %s: "
                    "%s; skipping",
                    f.path, submission_id, exc,
                )
                files_skipped += 1
                continue

            info = tarfile.TarInfo(name=f.path)
            info.size = len(data)
            # Use the blob's updated time if available; fall back to now.
            updated = getattr(blob, 'updated', None) or datetime.now(timezone.utc)
            try:
                info.mtime = int(updated.timestamp())
            except (AttributeError, TypeError):
                info.mtime = int(datetime.now(timezone.utc).timestamp())
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
            files_added += 1

    logger.info(
        "source_package: built tarball for submission %s "
        "(files_added=%d, files_skipped=%d, size_bytes=%d)",
        submission_id, files_added, files_skipped, buf.tell(),
    )

    buf.seek(0)
    return buf.getvalue()


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

    tar_bytes = _build_source_tarball(submission_id)
    stream = io.BytesIO(tar_bytes)
    stream.seek(0)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    filename = f"submission_{submission_id}-{timestamp}.tar.gz"
    headers = {
        "Content-Type": "application/gzip",
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
    }
    return stream, status.OK, headers
