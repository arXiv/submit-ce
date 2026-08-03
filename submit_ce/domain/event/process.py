"""Events related to external or long-running processes."""
import io
import logging
from datetime import datetime, timezone
import json
from typing import Optional

from dataclasses import field

from arxiv.files.object_store import FileDoesNotExist
from pydantic import BaseModel

from ..exceptions import InvalidEvent
from ..preview import Preview
from ..submission import Submission
from ..process import ProcessStatus
from ..uploads import SourceFormat
from .base import Event, EventWithSideEffect


from submit_ce.api import SubmitApi

logger = logging.getLogger(__name__)


class ProcessInfo(BaseModel):
    process_id: str
    """Identifier for the specific running process."""
    service_id: str
    """Identifier for the service running the process."""

class Result(BaseModel):
    """Result of a process such as compile."""
    status: ProcessStatus
    """The status of the process."""
    duration_sec: Optional[float]
    """Wall clock duration of the process in seconds."""
    utc_start_time: Optional[datetime]
    """UTC start time of the process."""
    url: Optional[str]
    """URL for the result of the process."""

class StartCompileSource(EventWithSideEffect):
    """Start compile the source of a submission."""

    NAME = "compile source"
    NAMED = "compiled source"

    source_content_id: Optional[str] = field(default=None)
    process: Optional[ProcessInfo] = field(default=None)
    result: Optional[Result] = field(default=None)

    def __post_init__(self) -> None:
        """Make sure our enums are in order."""
        super(StartCompileSource, self).__post_init__()

    def validate_pre_lock(self, submission: Submission) -> None:
        """Verify that we have a :class:`.ProcessStatus`."""
        if submission.uncompressed_size <= 0:
            raise InvalidEvent(self, "Compile source for the submission is empty.")

    def execute(self, api: 'SubmitApi', submission: Submission) -> None:
        """Do the actual compile."""
        result = api.get_compiler().start_compile(submission,
                                                  self.creator,
                                                  self.client,
                                                  api,
                                                  submission.submission_id)
        self.source_content_id = submission.submission_id
        # TODO add process info to Event?
        #self.process = process
        self.result = result

    def project(self, submission: Submission) -> Submission:
        """Add the process status to the submission."""
        assert self.created is not None
        #assert self.process is not None
        #assert self.status is not None and self.status in ProcessStatus.Status
        submission.processes.append(StartCompileSource(
            creator=self.creator,
            created=self.created,
            source_content_id=self.source_content_id,
            process=self.process,
            result=self.result,
        ))
        return submission


class StartPreflight(EventWithSideEffect):
    """Start preflight checks for a submission."""

    NAME = "start preflight"
    NAMED = "started preflight"

    source_content_id: Optional[str] = field(default=None)
    process: Optional[ProcessInfo] = field(default=None)
    result: Optional[Result] = field(default=None)

    def __post_init__(self) -> None:
        super(StartPreflight, self).__post_init__()

    def validate_pre_lock(self, submission: Submission) -> None:
        if not submission.submission_id:
            raise InvalidEvent(self, "Source content for preflight is empty.")

    def execute(self, api: 'SubmitApi', submission: Submission) -> None:
        """Run preflight checks."""
        result = api.get_compiler().start_preflight(
                submission,
                self.creator,
                self.client,
                api,
                submission.submission_id
        )
        self.source_content_id = submission.submission_id
        # TODO add process info to Event?
        #self.process = process
        self.result = result

    def project(self, submission: Submission) -> Submission:
        assert self.created is not None
        submission.processes.append(StartPreflight(
            creator=self.creator,
            created=self.created,
            source_content_id=self.source_content_id,
            process=self.process,
            result=self.result,
        ))
        return submission


class BuildSourcePackage(EventWithSideEffect):
    """Build the canonical ``<id>.tar.gz`` source package under the lock.

    The tar is assembled from the submission's current source files. By
    running as an :class:`.EventWithSideEffect`, ``SubmitApi.save`` holds the
    submission row lock for the duration of :meth:`execute`, so a concurrent
    upload or delete cannot change the file set mid-build and produce a
    package that mixes files which never coexisted on the submission. See the
    "critical section" design note in ``CLAUDE.md``.

    Carries no extra data (the side effect is the persisted ``<id>.tar.gz``),
    so it serializes and replays like any base event.
    """

    NAME = "build source package"
    NAMED = "built source package"

    def validate_pre_lock(self, submission: Submission) -> None:
        """The submission must exist to have a source package built."""
        if not submission.submission_id:
            raise InvalidEvent(
                self, "Cannot build source package: submission has no id.")

    def execute(self, api: 'SubmitApi', submission: Submission) -> None:
        """Build and persist ``<id>.tar.gz`` from current source, under lock."""
        api.get_file_store().write_source_package(submission.submission_id)

    def project(self, submission: Submission) -> Submission:
        """No submission-state change; the side effect is the stored tar."""
        return submission


class StoreZzrm(EventWithSideEffect):
    """Write ``00README.json`` into ``src/`` and invalidate the stale tar.

    The 00README build directives are derived from preflight and the
    submitter's decisions and written into the source directory as
    ``00README.json``. Writing a source file changes the file set the
    persisted ``<id>.tar.gz`` was built from, so that package is now
    stale (it predates 00README). By running as an
    :class:`.EventWithSideEffect`, ``SubmitApi.save`` holds the
    submission row lock for the duration of :meth:`execute`, so the
    write and the invalidation happen atomically and cannot interleave
    with a concurrent upload/delete. See the "critical section" design
    note in ``CLAUDE.md``.

    We *delete* the source package rather than rebuild it here, matching
    the lazy-invalidation pattern in
    ``domain/event/file.py::_common_file_change_execute``: the tar's
    consumers (preflight, the Download Package button) rebuild it before
    reading, and the finalize path rebuilds it for the QA snapshot. We
    deliberately do NOT call ``_common_file_change_execute`` -- that
    would also drop the preflight/user_decisions/directives we just
    generated, which are still valid for this file set.
    """

    NAME = "store 00README"
    NAMED = "stored 00README"

    zzrm: dict

    def validate_pre_lock(self, submission: Submission) -> None:
        """The submission must exist to have 00README written."""
        if not submission.submission_id:
            raise InvalidEvent(
                self, "Cannot store 00README: submission has no id.")

    def execute(self, api: 'SubmitApi', submission: Submission) -> None:
        """Write 00README.json to src/ and drop the now-stale tar, under lock."""
        file_store = api.get_file_store()
        file_store.store_zzrm(submission.submission_id, self.zzrm)
        file_store.delete_source_package(submission.submission_id)

    def project(self, submission: Submission) -> Submission:
        """No submission-state change; the side effects are the file writes."""
        return submission


def _stamp_text_and_link(submission: Submission) -> tuple[str, Optional[str]]:
    """Build the temporary submission stamp text and link.

    Mirrors ``arXiv::Submit::Util::stamp_and_link`` (arxiv-lib):
    ``arXiv:submit/<id>  [<primary category>]  <D Mon YYYY>`` -- two spaces
    between segments, category in brackets, day not zero-padded, three-letter
    month. A working submission has no submit_time yet, so the date is "now".
    """
    sid = submission.submission_id
    text = f"arXiv:submit/{sid}"
    try:
        category = submission.primary_category
    except Exception:
        category = None
    if category:
        text += f"  [{category}]"
    now = datetime.now(timezone.utc)
    text += f"  {now.day} {now.strftime('%b %Y')}"
    link = f"https://arxiv.org/submit/{sid}/pdf"
    return text, link


class InstallPdfPreview(EventWithSideEffect):
    """Install a PDF-only submission's PDF as its (stamped) preview, under lock.

    PDF-only submissions never run ``/convert``, so the stamped preview that
    TeX2PDF produces for TeX submissions must be produced on the Submit 2.0
    side. Running as an :class:`.EventWithSideEffect`, ``SubmitApi.save``
    holds the submission row lock for the whole operation (see the "critical
    section" note in ``CLAUDE.md``), so a concurrent upload/delete cannot
    change the file set mid-install. Under the lock this:

    1. calls the stamp service to watermark the uploaded PDF with the
       temporary submission stamp;
    2. writes the stamped PDF to the preview slot ``<id>.pdf`` -- or, if
       stamping fails, writes the unstamped bytes there so the preview slot is
       never empty;
    3. removes any stale ``<id>-nostamp.pdf`` left by a prior TeX compile
       (the submitter switched from TeX to PDF-only). PDF-only keeps its
       original PDF in ``src/``, so no dedicated unstamped copy is stored.
       [SUBMISSION-196]

    :meth:`project` marks the source processed and records the preview, the
    same as the pre-stamping ``ConfirmSourceProcessed`` install did.
    """

    NAME = "install pdf preview"
    NAMED = "installed pdf preview"

    source_checksum: str = field(default='')
    preview_checksum: str = field(default='')
    size_bytes: int = field(default=-1)
    stamped: bool = field(default=False)
    added: Optional[datetime] = field(default=None)

    def validate_pre_lock(self, submission: Submission) -> None:
        """Only applies to PDF-only submissions with an id."""
        if not submission.submission_id:
            raise InvalidEvent(
                self, "Cannot install PDF preview: submission has no id.")
        if submission.source_format != SourceFormat.PDF:
            raise InvalidEvent(
                self, "InstallPdfPreview only applies to PDF-only submissions.")

    def validate_under_lock(self, api: 'SubmitApi', submission: Submission) -> None:
        """Require exactly one PDF in the source workspace before installing.

        Runs inside the submission row lock, so the file set cannot change
        between this check and :meth:`execute`. For a PDF-only submission the
        workspace is a single lone PDF (see ``_infer_source_format``); if that
        invariant is violated we reject the event here rather than install a
        partial or absent preview -- the caller degrades gracefully on the
        resulting :class:`.InvalidEvent`. [SUBMISSION-196]
        """
        file_store = api.get_file_store()
        sid = submission.submission_id
        workspace = file_store.get_workspace(submission_id=sid)
        pdfs = [f for f in (workspace.files if workspace else [])
                if f.name.lower().endswith('.pdf')]
        if len(pdfs) != 1:
            raise InvalidEvent(
                self,
                f"Expected exactly one PDF for PDF-only submission {sid}, "
                f"found {len(pdfs)}.")

    def execute(self, api: 'SubmitApi', submission: Submission) -> None:
        """Stamp the uploaded PDF, install it as the preview, and drop any
        stale unstamped copy left by a prior TeX compile.

        :meth:`validate_under_lock` has already guaranteed exactly one PDF in
        the workspace under the same lock, so we take it directly.
        """
        file_store = api.get_file_store()
        sid = submission.submission_id
        workspace = file_store.get_workspace(submission_id=sid)
        pdf = [f for f in workspace.files
               if f.name.lower().endswith('.pdf')][0]
        source = file_store.get_source_file(sid, pdf.path)
        with source.open('rb') as stream:
            data = stream.read()

        # PDF-only keeps its original PDF in src/, so we don't persist a
        # redundant <id>-nostamp.pdf. If a prior TeX compile left an unstamped
        # PDF at the top-level slot (the submitter switched from TeX to
        # PDF-only), remove it so a stale copy can't linger. The stamping
        # fallback below uses the in-memory `data`, not this slot. [SUBMISSION-196]
        if file_store.does_nostamp_preview_exist(sid):
            file_store.delete_nostamp_preview(sid)
            logger.info(
                "InstallPdfPreview: removed stale unstamped PDF for %s", sid)

        text, link = _stamp_text_and_link(submission)
        stamped_bytes: Optional[bytes] = None
        try:
            stamped_bytes = api.get_compiler().stamp(data, text, link)
        except Exception as exc:
            logger.error(
                "InstallPdfPreview: stamping failed for %s: %s; installing "
                "unstamped preview instead", sid, exc)

        if stamped_bytes:
            self.preview_checksum = file_store.store_preview(
                sid, io.BytesIO(stamped_bytes))
            self.stamped = True
        else:
            self.preview_checksum = file_store.store_preview(
                sid, io.BytesIO(data))
            self.stamped = False

        self.source_checksum = pdf.crc32c
        self.size_bytes = pdf.bytes
        self.added = datetime.now(timezone.utc)

    def project(self, submission: Submission) -> Submission:
        """Mark the source processed and record the preview *artifact*.

        Records ``submission.preview`` (the preview PDF's checksums and size)
        and sets ``is_source_processed`` -- the same as
        ``ConfirmSourceProcessed`` did. This does NOT mark the preview as
        viewed: the "submitter reviewed the preview" bit
        (``submitter_confirmed_preview``, which gates Submit on the Confirm
        page) is set only by ``ConfirmPreview`` when the submitter actually
        opens ``/preview.pdf``. Recording ``submission.preview`` here is in
        fact the precondition for that step -- ``ConfirmPreview.validate``
        requires it to be present and checksum-matches it -- not a claim that
        the submitter previewed anything. [SUBMISSION-196]

        The one-PDF precondition is enforced in :meth:`validate_under_lock`, so
        an event that reaches ``project`` has installed a real preview via
        ``execute`` (``added`` is set).
        """
        submission.is_source_processed = True
        submission.preview = Preview(
            source_id=-1,
            source_checksum=self.source_checksum,
            preview_checksum=self.preview_checksum,
            size_bytes=self.size_bytes,
            added=self.added,
        )
        return submission


class StartDirectives(EventWithSideEffect):
    """Start directives generation for a submission."""

    NAME = "start directives"
    NAMED = "started directives"

    source_content_id: Optional[str] = field(default=None)
    process: Optional[ProcessInfo] = field(default=None)
    result: Optional[Result] = field(default=None)

    def validate_pre_lock(self, submission: Submission) -> None:
        if not submission.submission_id:
            raise InvalidEvent(self, "Source content for directives is empty.")

    def execute(self, api: 'SubmitApi', submission: Submission) -> None:
        result = api.get_compiler().start_directives(
                submission,
                self.creator,
                self.client,
                api,
                submission.submission_id
        )
        self.source_content_id = submission.submission_id
        self.result = result

    def project(self, submission: Submission) -> Submission:
        assert self.created is not None
        submission.processes.append(StartDirectives(
            creator=self.creator,
            created=self.created,
            source_content_id=self.source_content_id,
            process=self.process,
            result=self.result,
        ))
        return submission


class CompileStatus(Event):
    """Add the status of an external/long-running process to a submission."""

    NAME = "add status of a process"
    NAMED = "added status of a process"

    # Status = ProcessStatus.Status

    process: Optional[ProcessInfo] = field(default=None)
    result: Optional[Result] = field(default=None)

    def __post_init__(self) -> None:
        """Make sure our enums are in order."""
        super(CompileStatus, self).__post_init__()

    def validate_pre_lock(self, submission: Submission) -> None:
        """Verify that we have a :class:`.ProcessStatus`."""
        if self.process is None:
            raise InvalidEvent(self, "Must include process")
        if self.result is None:
            raise InvalidEvent(self, "Must include result")

    def project(self, submission: Submission) -> Submission:
        """Add the process status to the submission."""
        assert self.created is not None
        assert self.process is not None
        submission.processes.append(ProcessStatus(
            creator=self.creator,
            created=self.created,
            process=self.process,
            result=self.result,
        ))
        return submission


class PreflightStatus(Event):
    """Add the status of a preflight process to a submission."""

    NAME = "add status of preflight"
    NAMED = "added status of preflight"

    process: Optional[ProcessInfo] = field(default=None)
    result: Optional[Result] = field(default=None)

    def __post_init__(self) -> None:
        super(PreflightStatus, self).__post_init__()

    def validate_pre_lock(self, submission: Submission) -> None:
        if self.process is None:
            raise InvalidEvent(self, "Must include process")
        if self.result is None:
            raise InvalidEvent(self, "Must include result")

    def project(self, submission: Submission) -> Submission:
        assert self.created is not None
        assert self.process is not None
        submission.processes.append(ProcessStatus(
            creator=self.creator,
            created=self.created,
            process=self.process,
            result=self.result,
        ))
        return submission


def _protected_top_level_sources(decisions: dict) -> set[str]:
    """Filenames that must never be deleted: user-selected top-level TeX files.

    A source is treated as top-level when its ``usage`` is ``'toplevel'`` or is
    unset -- the Review Files form lists only top-level sources and does not
    always set an explicit usage. Handles one or more selected top-level files
    (SUBMISSION-209).
    """
    sources = (decisions or {}).get('sources') or []
    protected: set[str] = set()
    for src in sources:
        filename = src.get('filename')
        if filename and src.get('usage', 'toplevel') in (None, 'toplevel'):
            protected.add(filename)
    return protected


class SetDecisions(EventWithSideEffect):
    """Sets the decisions for the submission."""

    NAME = "set compile decisions"
    NAMED = "set compile decisions"

    # TODO make this a pydantic class
    decisions: dict

    files_to_delete: list[str]

    bytes_removed: int = 0

    def validate_pre_lock(self, submission: Submission) -> None:
        if not self.decisions:
            raise InvalidEvent(self, "Must include decisions information")
        # TODO better validation of preflight data or just handled by pydantic?
        # Maybe have the prefight be a dict on self then validate it here and raise errors?

    def validate_under_lock(self, api: SubmitApi, submission: Submission) -> None:
        blob = api.get_file_store().get_user_decisions(submission.submission_id)
        if isinstance(blob, FileDoesNotExist):
            return

        existing_preflight = json.loads(blob.download_as_text())
        decisions_changed = self.decisions != existing_preflight
        has_changes = bool(self.files_to_delete) or decisions_changed
        # TODO we could check if the files_to_delete actually exist
        if not has_changes:
            raise InvalidEvent(self, "No changes to save")

    def execute(self, api: SubmitApi, submission: Submission) -> None:
        file_store = api.get_file_store()
        file_store.store_user_decisions(submission.submission_id, self.decisions)
        # Directives depend on the selection (compiler / top-level), so always drop
        # them here; the controller regenerates them from the new decisions.
        file_store.delete_directives(submission.submission_id)
        # Preflight analyses the *file set*, not the selection. Only invalidate it
        # when files are actually removed (G29 / SUBMISSION-215). A selection-only
        # change (compiler / top-level) leaves the report valid, so the submitter is
        # not bounced back to Upload for a needless re-scan.
        if self.files_to_delete:
            file_store.delete_preflight(submission.submission_id)
        # Authoritative guard (SUBMISSION-209): never delete a file the user has
        # selected as a top-level TeX file -- that's what we're about to compile.
        # Runs under the submission row lock taken by save(), so it can't race a
        # concurrent decisions change.
        protected = _protected_top_level_sources(self.decisions)
        for path in self.files_to_delete:
            if path in protected:
                logger.warning(
                    "Refusing to delete selected top-level file %s for "
                    "submission %s", path, submission.submission_id)
                continue
            file = file_store.delete_source_file(submission.submission_id, path)
            if file:
                self.bytes_removed += file.bytes

    def project(self, submission: Submission) -> Submission:
        submission.uncompressed_size -= self.bytes_removed
        return submission


class SetDirectivesAndCleanup(EventWithSideEffect):
    """Prepare the submission for a (re)run of preflight.

    Performed atomically under the submission row lock taken by
    `SubmitApi.save()`:

    1. If a 00README.json ("zzrm") was found and converted to
       user_decisions before this event was dispatched, persist
       those user_decisions and delete the source 00README.json.
    2. Delete the stale directives.json so the upcoming preflight
       produces a fresh set.

    This event is invoked from review.py's `_load_or_create_preflight`
    immediately before triggering `StartPreflight`, so the cleanup
    cannot interleave with a concurrent upload on the same
    submission.
    """

    NAME = "set directives and cleanup"
    NAMED = "directives reset and cleaned up"

    # If provided, the value is written as user_decisions.json and
    # the source 00README.json is deleted. If None, user_decisions
    # and 00README.json are left untouched.
    user_decisions_from_zzrm: Optional[dict] = None

    def validate_pre_lock(self, submission: Submission) -> None:
        # No input invariants: the event is always safe to dispatch
        # from `_load_or_create_preflight`; an absent zzrm just means
        # "skip the user_decisions seed step."
        pass

    def execute(self, api: SubmitApi, submission: Submission) -> None:
        file_store = api.get_file_store()
        if self.user_decisions_from_zzrm is not None:
            file_store.store_user_decisions(
                submission.submission_id, self.user_decisions_from_zzrm
            )
            file_store.delete_source_file(
                submission.submission_id, '00README.json'
            )
        # user_decisions + preflight + compile logs -> directives.json
        file_store.delete_directives(submission.submission_id)

    def project(self, submission: Submission) -> Submission:
        return submission
