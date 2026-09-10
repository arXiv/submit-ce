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

import httpx
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
    SetDirectivesAndCleanup,
    StartCompileSource,
    StartDirectives,
    StartPreflight,
    StoreZzrm,
)
from submit_ce.domain.exceptions import InvalidEvent, SaveError
from submit_ce.domain.compilation import Compilation
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

DEFAULT_TEXLIVE_VERSION = Compilation.CompilerVersion.TEXLIVE_2025.value
"""TeX Live release to compile against when nobody has chosen one.

The review form offers this choice; a deposit has no form, so the worker takes the
same fallback the form itself uses (``review.py:296-300``).
"""

RETRYABLE_STATUSES = (401, 403, 408, 429)
"""4xx codes that are worth another pass.

401/403 are about the caller's credentials -- expired ADC, a service account
missing a role -- and say nothing about the deposit. 408 and 429 are explicit
"try again" answers. Everything else in the 4xx range is a statement about the
request, which will not change on its own.
"""

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
    permanent: bool = False
    """Whether retrying could ever help.

    A permanent failure is one where the same input will produce the same answer:
    tex2pdf rejecting the source with a 4xx, or preflight finding no usable format.
    The caller records these so the submission stops being a candidate; a transient
    failure is left alone and picked up next pass.
    """

    def __str__(self) -> str:
        done = ", ".join(self.steps) if self.steps else "nothing to do"
        if not self.error:
            return f"submission {self.submission_id}: {done}"
        kind = "PERMANENT" if self.permanent else "retryable"
        return f"submission {self.submission_id}: {done} -- {kind}: {self.error}"


def _body(response) -> str:
    """A short, single-line excerpt of an error response, for the log and tracking."""
    try:
        text = response.text or ""
    except Exception:            # a streamed or already-closed response
        return "<unreadable>"
    return " ".join(text.split())[:200]


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


def _zzrm_decisions(api: SubmitApi, submission_id: str) -> Optional[dict]:
    """User decisions from a ``00README.json`` the depositor shipped, if any.

    Depositors can include one in their zip to say which file is top level and
    which compiler to use -- the SWORD equivalent of the choices the review form
    collects interactively.
    """
    blob = api.get_file_store().get_source_file(submission_id=submission_id,
                                                path="00README.json")
    if isinstance(blob, FileDoesNotExist):
        return None
    try:
        return DirectiveManager.convert_zzrm_to_user_decisions(
            json.loads(blob.download_as_text()))
    except (ValueError, OSError, KeyError) as exc:
        logger.warning("00README.json for %s is unusable: %s", submission_id, exc)
        return None


def _user_decisions(api: SubmitApi, submission_id: str) -> Optional[dict]:
    """Decisions persisted by `SetDirectivesAndCleanup`, for a resumed pass.

    That event converts the depositor's ``00README.json`` into
    ``user_decisions.json`` and *deletes the original*, so on any pass after the
    first this is the only surviving record of what they asked for.
    """
    blob = api.get_file_store().get_user_decisions(submission_id=submission_id)
    if isinstance(blob, FileDoesNotExist):
        return None
    try:
        return json.loads(blob.download_as_text())
    except (ValueError, OSError) as exc:
        logger.warning("user_decisions for %s is unreadable: %s",
                       submission_id, exc)
        return None


def _has_usable_zzrm(api: SubmitApi, submission_id: str) -> bool:
    """Whether ``src/00README.json`` exists and says enough to compile.

    Existence alone is not enough: tex2pdf answers "ZZRM missing **or
    underspecified**", and a file without ``texlive_version`` is the second case.
    """
    blob = api.get_file_store().get_source_file(submission_id=submission_id,
                                                path="00README.json")
    if isinstance(blob, FileDoesNotExist):
        return False
    try:
        return bool(json.loads(blob.download_as_text()).get("texlive_version"))
    except (ValueError, OSError):
        return False


def _make_directives(api: SubmitApi, submission: Submission, creator: User,
                     client: Client) -> bool:
    """Generate ``directives.json``, which tex2pdf needs before it will compile.

    Interactively this is the *human* step: the review form is where a submitter
    picks the top-level TeX file and the compiler, and confirming it runs
    `StartDirectives` (``review.py``'s ``_load_or_create_directives``). A deposit
    has nobody to ask, so the worker takes tex2pdf's default answer.

    Skipping this is what makes ``/convert`` reply
    ``422 {"message":"ZZRM missing or underspecified."}``.
    """
    if submission.source_format not in NEEDS_COMPILE:
        return False

    from tex2pdf_tools.preflight import PreflightResponse
    from tex2pdf_tools.zerozeroreadme import ZeroZeroReadMe

    submission_id = str(submission.submission_id)
    store = api.get_file_store()
    did_work = False

    # Read the depositor's choices before the cleanup below removes them, and fall
    # back to user_decisions.json on a resumed pass, where cleanup has already run.
    decisions = _zzrm_decisions(api, submission_id) or _user_decisions(api,
                                                                      submission_id)

    # Two artefacts, guarded separately: a pass that wrote one and died must not
    # skip the other on the way back. Guarding both on directives.json alone left
    # 00README.json unwritten forever, and compile kept answering 422.
    if not store.does_directives_exist(submission_id):
        # Mirrors the UI: persist any 00README the depositor shipped as user
        # decisions and clear a stale directives.json, both under the row lock,
        # then ask tex2pdf for the directives themselves.
        api.save(SetDirectivesAndCleanup(
            creator=creator, client=client, user_decisions_from_zzrm=decisions),
            submission_id=submission_id)
        api.save(StartDirectives(creator=creator, client=client),
                 submission_id=submission_id)
        did_work = True

    # The part ``/convert`` actually requires. "ZZRM missing or underspecified"
    # is about ``00README.json`` *in the source*, not the ``directives.json`` the
    # call above produces. Interactively this is written when the submitter
    # confirms the review form (``review.py``, ``StoreZzrm``); the answers come
    # from preflight instead of from a person here.
    if not _has_usable_zzrm(api, submission_id):
        preflight = _preflight_data(api, submission_id)
        if preflight is None:
            raise InvalidEvent(
                StoreZzrm(creator=creator, client=client, zzrm={}),
                "no preflight data from which to build 00README.json")

        zzrm = ZeroZeroReadMe()
        if decisions:
            zzrm.from_dict(decisions)
        zzrm.update_from_preflight(PreflightResponse(**preflight))

        # `ZeroZeroReadMe` leaves texlive_version None and `update_from_preflight`
        # does not fill it, so without this the file is written *without* the
        # field -- which tex2pdf reports as "ZZRM missing or underspecified" and,
        # once the file exists, as a bare 403. Interactively the value comes from
        # the review form's compiler_version, which itself falls back to this same
        # constant (``review.py:296-300``).
        if not zzrm.texlive_version:
            zzrm.texlive_version = DEFAULT_TEXLIVE_VERSION

        api.save(StoreZzrm(creator=creator, client=client, zzrm=zzrm.to_dict()),
                 submission_id=submission_id)
        did_work = True

    return did_work


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

        if _make_directives(api, submission, creator, client):
            steps.append("directives")
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
        # continues or stops in the same place. These are permanent: every one is
        # raised from a check on the submission's own state, which the next pass
        # would evaluate identically.
        logger.info("submission %s stopped after %s: %s",
                    submission_id, steps or "no steps", exc)
        return Outcome(int(submission_id), steps, finalized=False,
                       error=str(exc), permanent=True)

    except httpx.HTTPStatusError as exc:
        # tex2pdf refused. Most 4xx are about the source -- "ZZRM missing or
        # underspecified", an unusable file -- and resending it unchanged gets the
        # same answer, so retrying is just noise against their service.
        #
        # 401 and 403 are the exception: they are about *our* credentials, not the
        # deposit. Expired ADC produces a 403 against a perfectly good submission,
        # and marking that permanent would sideline it until someone noticed and
        # cleared the tracking row by hand. Treat them as retryable so the backlog
        # simply resumes once the credentials are fixed.
        status = exc.response.status_code
        permanent = 400 <= status < 500 and status not in RETRYABLE_STATUSES
        detail = f"compile service returned {status}: {_body(exc.response)}"
        logger.info("submission %s stopped after %s: %s",
                    submission_id, steps or "no steps", detail)
        return Outcome(int(submission_id), steps, finalized=False,
                       error=detail, permanent=permanent)

    except httpx.RequestError as exc:
        # Never reached the service: DNS, connection reset, timeout. Always worth
        # another pass.
        detail = f"could not reach the compile service: {exc}"
        logger.warning("submission %s: %s", submission_id, detail)
        return Outcome(int(submission_id), steps, finalized=False, error=detail)
