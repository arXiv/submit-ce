from __future__ import annotations
from pydantic import ConfigDict, Field, WithJsonSchema
from typing import TYPE_CHECKING, List, Annotated, Optional

if TYPE_CHECKING:
    from submit_ce.api.submit import SubmitApi

from . import validators
from .base import EventWithSideEffect
from ..submission import Submission
from ..uploads import SubmitFile

import logging
logger = logging.getLogger(__name__)

def _common_file_change_project(submission: Submission) -> None:
    """Common changes during `project` to submission when any file change happens."""
    submission.submitter_confirmed_preview = False


def _common_file_change_execute(api: SubmitApi, submission: Submission) -> None:
    """Common changes during `execute` when any file change happens.

    Any change to the source workspace invalidates the analysis chain
    that was built from the previous state of the files:

    * **source_package** -- the persisted ``<id>.tar.gz`` snapshot of
      the source directory. The preflight API
      (``CompileApiService.start_preflight``) hands this path to
      tex2pdf as the ``source`` query param, so if it lingers past a
      file change tex2pdf scans a stale snapshot and Review Files
      shows the old file list. We delete it here; the next
      ``start_preflight`` call rebuilds it fresh from ``src/``. (The
      same archive is rebuilt by ``compile_at_gcp.py`` on a successful
      compile, so the compile-time path is unaffected.)
    * **preflight** -- the per-file scan that detects compiler, top-level
      TeX, issues, etc. Must be re-run against the new file list.
    * **user_decisions** -- captures the user's selections (source_file,
      compiler, marked-for-deletion) made on the Review Files step.
      Those selections may reference files that no longer exist after
      the change, so we drop them and let the user re-select.
    * **directives** -- the combined preflight + user_decisions output
      that drives compilation. With both of its inputs invalidated,
      this is also stale.
    * **preview** -- the compiled PDF that was produced from the
      previous source.

    Submit 1.5 had separate ``clear_preflight`` and
    ``clear_directives_data`` routines in ``Submit.pm`` that were
    called from various file-change paths; this is the 2.0 equivalent
    consolidated into one place so all four file events
    (UploadArchive / UploadFiles / RemoveFiles / RemoveAllFiles) get
    consistent invalidation. Skipping any of these leads to stale data
    being shown on Review Files even though the workspace itself is
    current.

    Note: we delete here (cheap, one bucket call per event) rather
    than rebuild here. Rebuilding the tar inside each file event
    would be quadratic for multi-file uploads -- N AddFiles events
    would each download all N files and reupload, for O(N^2) bucket
    traffic, with only the last build mattering. Lazy rebuild in
    ``start_preflight`` keeps the cost at one build per preflight
    call regardless of how many file events preceded it.
    """
    file_store = api.get_file_store()
    sid = str(submission.submission_id)
    file_store.delete_source_package(sid)
    file_store.delete_preflight(sid)
    file_store.delete_user_decisions(sid)
    file_store.delete_directives(sid)
    file_store.delete_preview(sid)


class UploadArchive(EventWithSideEffect):
    """Uploads a zip or tgz file to the workspace, unpacking all the files."""

    NAME = "upload and unpack archive"
    NAMED = "archive unpacked and added"

    file: Optional[Annotated[SubmitFile, WithJsonSchema({'type': 'object'})]] = Field(default=None, exclude=True)
    """File to upload. Excluded from serialization, so `None` after replay from event history."""

    bytes_added: int = 0
    """Bytes added by uploading this archive."""

    def validate(self, submission: Submission) -> None:
        validators.submission_is_not_finalized(self, submission)

    def execute(self, api: SubmitApi, submission: Submission) -> None:
        """Upload the new files using the file store."""
        files = api.get_file_store().store_source_package(str(submission.submission_id), self.file, 4098)
        self.bytes_added = sum([file.bytes for file in files])
        _common_file_change_execute(api, submission)

    def project(self, submission: Submission) -> Submission:
        submission.uncompressed_size += self.bytes_added
        _common_file_change_project(submission)
        return submission


class UploadFiles(EventWithSideEffect):
    """Add files to the upload workspace for this submission.

    Also initializes the upload package if none exists yet.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    NAME = "add files"
    NAMED = "files added"

    files: List[Annotated[SubmitFile, WithJsonSchema({'type': 'object'})]] = \
        Field(default_factory=list, exclude=True)
    bytes_added: int = 0

    def validate(self, submission: Submission) -> None:
        validators.submission_is_not_finalized(self, submission)

    def execute(self, api: SubmitApi, submission: Submission) -> None:
        """Upload the new files using the file store."""
        file_store = api.get_file_store()
        for f in self.files:
            stat=file_store.store_source_file(str(submission.submission_id), f, chunk_size=4096)
            self.bytes_added += stat.bytes
        _common_file_change_execute(api, submission)

    def project(self, submission: Submission) -> Submission:
        submission.uncompressed_size += self.bytes_added
        _common_file_change_project(submission)
        return submission


class RemoveFiles(EventWithSideEffect):
    """Remove files from the upload workspace for this submission."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    NAME = "remove files"
    NAMED = "files removed"

    files: List[str] = Field(default_factory=List)
    """name of files to remove."""

    bytes_removed:int = 0
    """Bytes removed by removing these files."""

    def validate(self, submission: Submission) -> None:
        validators.submission_is_not_finalized(self, submission)

    def execute(self, api: SubmitApi, submission: Submission) -> None:
        """Remove the specified files from the file store."""

        file_store = api.get_file_store()
        for filename in self.files:
            file = file_store.delete_source_file(str(submission.submission_id), filename)
            if file:
                self.bytes_removed += file.bytes

        _common_file_change_execute(api, submission)

    def project(self, submission: Submission) -> Submission:
        submission.uncompressed_size -= self.bytes_removed
        _common_file_change_project(submission)
        return submission


class RemoveAllFiles(EventWithSideEffect):
    """Remove all files from the upload workspace for this submission."""

    NAME = "remove all files"
    NAMED = "all files removed"

    def validate(self, submission: Submission) -> None:
        validators.submission_is_not_finalized(self, submission)

    def execute(self, api: SubmitApi, submission: Submission) -> None:
        """Remove the entire upload workspace using the file store."""
        file_store = api.get_file_store()
        file_store.delete_all_source_files(str(submission.submission_id))
        _common_file_change_execute(api, submission)

    def project(self, submission: Submission) -> Submission:
        submission.source_format = None
        submission.uncompressed_size = 0
        _common_file_change_project(submission)
        return submission
