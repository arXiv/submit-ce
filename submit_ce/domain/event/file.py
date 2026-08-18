from __future__ import annotations
from pydantic import ConfigDict, Field, WithJsonSchema
from typing import TYPE_CHECKING, List, Annotated, Optional

from submit_ce.domain.exceptions import InvalidEvent

if TYPE_CHECKING:
    from submit_ce.api.submit import SubmitApi

from . import validators
from .base import EventWithSideEffect
from ..submission import Submission
from ..uploads import FileStatus, SubmitFile
from .. import size_limits

import logging
logger = logging.getLogger(__name__)

def _common_file_change_project(submission: Submission) -> None:
    """Common state changes during `project` when any file change happens.

    A file change invalidates the previous processing outcome: the compiled
    preview no longer reflects the current source (its file and the compile log
    are removed in `_common_file_change_execute`). So we mark the submission
    unprocessed -- `is_source_processed=False`, which round-trips to the legacy
    `must_process=1` column -- and drop the now-stale `submission.preview`,
    mirroring `UnConfirmSourceProcessed`. Without this the Process stage stays
    "complete" after an edit (letting the submitter skip recompilation) and
    `submission.preview` dangles at a deleted file. Applies to both TeX and
    PDF-only submissions, since all file-change events route through here.
    [SUBMISSION-207]
    """
    submission.submitter_confirmed_preview = False
    submission.is_source_processed = False
    submission.preview = None


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
    * **compile_log** -- the TeX compiler log produced alongside that
      preview. It belongs to the previous source, so leaving it behind
      lets the Process page render a stale log (from a compile of files
      that no longer exist) even though the preview it described is gone.
      [SUBMISSION-75]

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
    file_store.delete_compile_log(sid)


def _add_evaluate_oversize(api: SubmitApi,
                           submission: Submission,
                           bytes_added:int,
                           files: list[FileStatus],
                          ) -> list[size_limits.OversizeReason]:
    """Figure out if any oversize problems due to file additions."""
    per_file = {file.path: file.bytes for file in files}
    total = submission.uncompressed_size + bytes_added
    category = (submission.primary_classification.category
                if submission.primary_classification else None)
    return size_limits.check_sizes(total, per_file, primary_category=category,
                                   limits=api.get_size_limits())


def _workspace_evaluate_oversize(api: SubmitApi, submission: Submission) -> list[size_limits.OversizeReason]:
    """Measure the current workspace against the configured size limits.

    Reads the authoritative post-change workspace so the flag reflects *all*
    current files, not just the ones this event touched. This causes more api
    requests than `_add_evaluate_oversize`
    """
    workspace = api.get_file_store().get_workspace(str(submission.submission_id))
    if workspace is None:
        return []
    per_file = {file.path: file.bytes for file in workspace.files}
    total = workspace.size or 0
    category = (submission.primary_classification.category
                if submission.primary_classification else None)
    return size_limits.check_sizes(total, per_file, primary_category=category,
                                   limits=api.get_size_limits())



class UploadArchive(EventWithSideEffect):
    """Uploads a zip or tgz file to the workspace, unpacking all the files."""

    NAME = "upload and unpack archive"
    NAMED = "archive unpacked and added"

    file: Optional[Annotated[SubmitFile, WithJsonSchema({'type': 'object'})]] = Field(default=None, exclude=True)
    """File to upload. Excluded from serialization, so `None` after replay from event history."""

    bytes_added: int = 0
    """Bytes added by uploading this archive."""

    oversize: list[size_limits.OversizeReason] = []
    """`OversizeReason` instances after this change (set in execute)."""

    def validate_pre_lock(self, submission: Submission) -> None:
        validators.submission_is_not_finalized(self, submission)
        if not self.file:
            raise InvalidEvent(self, "Must upload a file")

    def execute(self, api: SubmitApi, submission: Submission) -> None:
        """Upload the new files using the file store."""
        if not self.file:
            raise RuntimeError("File must be set")
        files = api.get_file_store().store_source_package(str(submission.submission_id), self.file, 4098)
        self.bytes_added = sum([file.bytes for file in files])
        _common_file_change_execute(api, submission)
        self.oversize = _add_evaluate_oversize(api, submission, self.bytes_added, files)

    def project(self, submission: Submission) -> Submission:
        submission.uncompressed_size += self.bytes_added
        submission.is_oversize = bool(self.oversize)
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

    oversize: list[size_limits.OversizeReason] = []
    """`OversizeReason` instances after this change (set in execute)."""

    def validate_pre_lock(self, submission: Submission) -> None:
        validators.submission_is_not_finalized(self, submission)

    def execute(self, api: SubmitApi, submission: Submission) -> None:
        """Upload the new files using the file store."""
        file_store = api.get_file_store()
        stats = []
        for f in self.files:
            stat=file_store.store_source_file(str(submission.submission_id), f, chunk_size=4096)
            stats.append(stat)
            self.bytes_added += stat.bytes
        _common_file_change_execute(api, submission)
        self.oversize = _add_evaluate_oversize(api, submission, self.bytes_added, stats)

    def project(self, submission: Submission) -> Submission:
        submission.uncompressed_size += self.bytes_added
        submission.is_oversize = bool(self.oversize)
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

    oversize: list[size_limits.OversizeReason] = []
    """`OversizeReason` instances after this change (set in execute)."""

    def validate_pre_lock(self, submission: Submission) -> None:
        validators.submission_is_not_finalized(self, submission)

    def execute(self, api: SubmitApi, submission: Submission) -> None:
        """Remove the specified files from the file store."""

        file_store = api.get_file_store()
        for filename in self.files:
            file = file_store.delete_source_file(str(submission.submission_id), filename)
            if file:
                self.bytes_removed += file.bytes

        _common_file_change_execute(api, submission)
        self.oversize = _workspace_evaluate_oversize(api, submission)

    def project(self, submission: Submission) -> Submission:
        submission.uncompressed_size -= self.bytes_removed
        submission.is_oversize = bool(self.oversize)
        _common_file_change_project(submission)
        return submission


class RemoveAllFiles(EventWithSideEffect):
    """Remove all files from the upload workspace for this submission."""

    NAME = "remove all files"
    NAMED = "all files removed"

    def validate_pre_lock(self, submission: Submission) -> None:
        validators.submission_is_not_finalized(self, submission)

    def execute(self, api: SubmitApi, submission: Submission) -> None:
        """Remove the entire upload workspace using the file store."""
        file_store = api.get_file_store()
        file_store.delete_all_source_files(str(submission.submission_id))
        _common_file_change_execute(api, submission)

    def project(self, submission: Submission) -> Submission:
        submission.source_format = None
        submission.uncompressed_size = 0
        submission.is_oversize = False
        _common_file_change_project(submission)
        return submission
