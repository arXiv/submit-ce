"""Carry a SWORD deposit from "files uploaded" to "submitted".

`submit_ce.sword.ingest` stops once the submission exists and its files are in the
workspace. Everything after that -- work out what the source *is*, compile it, and
finalize -- is done here, because it takes minutes and cannot happen inside the
deposit request.

The five steps are the ones the Flask UI walks a submitter through, driven as the
same domain events so a deposited submission is indistinguishable from an
interactive one::

    StartPreflight          analyse the source        -> gcp_preflight.json
    SetSourceFormat         from preflight's `lang`
    StartCompileSource      compile it                -> preview
      or InstallPdfPreview  (PDF-only needs no compile)
    ConfirmSourceProcessed  the source is usable
    FinalizeSubmission      queue it for announcement

Why this is not in the request
------------------------------
``start_preflight`` and ``start_compile`` are blocking HTTP calls to tex2pdf, each
with ``COMPILE_API_*_TIMEOUT`` of 840 seconds, and each runs as an
`EventWithSideEffect` inside ``SubmitApi.save`` -- which holds
``SELECT ... FOR UPDATE`` on the submission row for the duration. Worst case is
close to half an hour with the row locked. SWORD's 202 promises asynchronous
ingestion precisely so this can happen out of band.

Resumable by construction
-------------------------
Every step is guarded by a check on state that survives a restart -- a file in the
store, or a field on the submission -- rather than by anything held in memory. A
worker killed mid-compile leaves no lock and no marker: the next pass re-reads the
submission and picks up at the first step that has not happened. `advance` is safe
to call repeatedly on the same submission.

Finalizing sends mail
---------------------
``FinalizeSubmission`` carries `EmailSubmitterFinalizeMsg` and
`EmailModeratorsFinalizeMsg` as consequences, so completing this ladder emails the
depositor and the moderators for that archive -- the same messages an interactive
submission sends. It can also auto-hold, which is how an oversize submission is
caught.
"""

import json
import logging
from dataclasses import dataclass
from typing import List, Optional

from arxiv.files import FileDoesNotExist

from submit_ce.api import SubmitApi
from submit_ce.domain import Event, Submission
from submit_ce.domain.agent import Client, User
from submit_ce.domain.event import (
    ConfirmSourceProcessed,
    FinalizeSubmission,
    SetSourceFormat,
)
from submit_ce.domain.event.process import (
    InstallPdfPreview,
    StartCompileSource,
    StartPreflight,
)
from submit_ce.domain.exceptions import InvalidEvent, SaveError
from submit_ce.domain.uploads import SourceFormat
from submit_ce.implementations.compile.directive_manager import DirectiveManager
from submit_ce.ui.workflow import conditions

logger = logging.getLogger(__name__)

COMPILE_PLACEHOLDER = "BOGUS"
"""``StartCompileSource.source_content_id``.

The UI passes this same placeholder from its auto-compile path
(``ui/controllers/new/process.py``); the compile service takes the source from the
submission's workspace and never reads the field.
"""

UNSET_FORMATS = (None, SourceFormat.UNKNOWN, SourceFormat.INVALID)
"""Source formats that mean "preflight has not usefully answered yet"."""

NEEDS_COMPILE = (SourceFormat.TEX, SourceFormat.PDFTEX)
"""Formats that go through tex2pdf. PDF is installed directly; HTML and the rest
need no processing step."""

NEEDS_PREVIEW = NEEDS_COMPILE + (SourceFormat.PDF,)
"""Formats that must end up with a preview before the submission may be finalized.

Nothing in the domain enforces this -- `FinalizeSubmission` will happily queue a
submission whose compile produced no PDF. Interactively that cannot happen, because
the Submit button is gated on the preview; a worker has no such gate and would
otherwise push a PDF-less paper into the announcement queue on the strength of a
failed compile."""


@dataclass(frozen=True)
class Outcome:
    """What one pass over a submission accomplished."""

    submission_id: int
    steps: List[str]
    finalized: bool
    error: Optional[str] = None

    def __str__(self) -> str:
        done = ", ".join(self.steps) if self.steps else "nothing to do"
        tail = f" -- FAILED: {self.error}" if self.error else ""
        return f"submission {self.submission_id}: {done}{tail}"


def _preflight_data(api: SubmitApi, submission_id: str) -> Optional[dict]:
    """The parsed ``gcp_preflight.json``, or None when it is not there."""
    blob = api.get_file_store().get_preflight(submission_id=submission_id)
    if isinstance(blob, FileDoesNotExist):
        return None
    try:
        return json.loads(blob.download_as_text())
    except (ValueError, OSError) as exc:
        logger.warning("preflight for %s is unreadable: %s", submission_id, exc)
        return None


def _run_preflight(api: SubmitApi, submission_id: str, creator: User,
                   client: Client) -> bool:
    """Analyse the source. Returns True when it ran."""
    if api.get_file_store().does_preflight_exist(submission_id):
        return False
    api.save(StartPreflight(creator=creator, client=client),
             submission_id=submission_id)
    return True


def _set_source_format(api: SubmitApi, submission: Submission,
                       creator: User, client: Client) -> Optional[str]:
    """Record what preflight decided the source is.

    Returns the format it stored, or None when it was already set. The value is
    returned rather than read back off ``submission`` because the caller's copy
    predates the save.

    Raises `InvalidEvent` if preflight produced no usable ``lang``: without a
    source format the submission can never be finalized, so this is a dead end
    rather than something to retry forever.
    """
    if submission.source_format not in UNSET_FORMATS:
        return None

    submission_id = str(submission.submission_id)
    lang = DirectiveManager.get_lang_from_preflight(
        _preflight_data(api, submission_id))
    if lang is None:
        raise InvalidEvent(
            SetSourceFormat(creator=creator, client=client),
            "preflight detected no usable source format")

    api.save(SetSourceFormat(creator=creator, client=client, source_format=lang),
             submission_id=submission_id)
    return lang


def _produce_preview(api: SubmitApi, submission: Submission,
                     events: List[Event], creator: User,
                     client: Client) -> bool:
    """Compile, or install a PDF, so there is something to announce.

    Returns True when work was done. Formats that need no processing (HTML and
    friends) are a no-op -- they are already their own preview.
    """
    submission_id = str(submission.submission_id)
    store = api.get_file_store()
    if store.does_preview_exist(submission_id):
        return False

    if submission.source_format == SourceFormat.PDF:
        api.save(InstallPdfPreview(creator=creator, client=client),
                 submission_id=submission_id)
        return True

    if submission.source_format not in NEEDS_COMPILE:
        return False

    # A compile that failed on TeX errors leaves a StartCompileSource event and no
    # preview. Recompiling identical source would fail identically, so stop and let
    # the failure be reported rather than looping on every pass.
    if conditions.has_compiled_current_source(submission, events):
        raise InvalidEvent(
            StartCompileSource(creator=creator, client=client,
                               source_content_id=COMPILE_PLACEHOLDER),
            "compile already attempted for this source and produced no preview")

    api.save(StartCompileSource(creator=creator, client=client,
                                source_content_id=COMPILE_PLACEHOLDER),
             submission_id=submission_id)
    store.uncompress_compile_tarball(submission_id)
    return True


def _require_preview(api: SubmitApi, submission: Submission) -> None:
    """Refuse to finalize a submission that has nothing to announce.

    The compile step gives up rather than retrying identical broken source, which
    leaves the submission with a source format and no PDF. Without this the ladder
    would sail on to `FinalizeSubmission` and queue it for announcement.
    """
    if submission.source_format not in NEEDS_PREVIEW:
        return
    submission_id = str(submission.submission_id)
    if not api.get_file_store().does_preview_exist(submission_id):
        raise InvalidEvent(
            FinalizeSubmission(creator=submission.owner),
            f"no preview for {submission.source_format} source; refusing to "
            "finalize a submission with nothing to announce")


def advance(api: SubmitApi, submission_id: str, *, creator: User,
            client: Client) -> Outcome:
    """Move one submission as far along the ladder as it will go.

    Idempotent: each step checks whether it has already happened, so calling this
    on a finished submission does nothing, and calling it on a half-processed one
    resumes. Every step is attempted in a single pass, so an untouched submission
    can go all the way to finalized in one call.
    """
    steps: List[str] = []
    submission, events = api.get_with_history(submission_id)

    if submission.is_finalized:
        return Outcome(int(submission_id), steps, finalized=True)

    try:
        if _run_preflight(api, submission_id, creator, client):
            steps.append("preflight")
            submission, events = api.get_with_history(submission_id)

        stored_format = _set_source_format(api, submission, creator, client)
        if stored_format is not None:
            steps.append(f"source_format={stored_format}")
            submission, events = api.get_with_history(submission_id)

        if _produce_preview(api, submission, events, creator, client):
            steps.append("preview")
            submission, events = api.get_with_history(submission_id)

        _require_preview(api, submission)

        if not submission.is_source_processed:
            api.save(ConfirmSourceProcessed(creator=creator, client=client),
                     submission_id=submission_id)
            steps.append("source_processed")
            submission, events = api.get_with_history(submission_id)

        api.save(FinalizeSubmission(creator=creator), submission_id=submission_id)
        steps.append("finalized")
        return Outcome(int(submission_id), steps, finalized=True)

    except (InvalidEvent, SaveError) as exc:
        # A precondition that is not yet met, or a step that cannot succeed.
        # Whatever completed still stands; the next pass re-reads state and either
        # continues or stops in the same place.
        logger.info("submission %s stopped after %s: %s",
                    submission_id, steps or "no steps", exc)
        return Outcome(int(submission_id), steps, finalized=False,
                       error=str(exc))
