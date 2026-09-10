"""The ladder that carries a deposit from "files uploaded" to "submitted".

`submit_ce.sword.worker.advance` is the piece `submit_ce.sword.ingest` deliberately
leaves out. These drive it against `MockCompileMimesisPdf`, which writes the same
shape of ``gcp_preflight.json`` the real tex2pdf returns and produces a PDF, so the
steps run for real without touching the compile service.
"""

import pytest
from arxiv.db import Session

from submit_ce.domain.uploads import SourceFormat
from submit_ce.implementations.compile.mock_compile_mimesis_pdf import (
    MockCompileMimesisPdf,
)
from submit_ce.sword import worker
from submit_ce.sword.app import depositor_user
from submit_ce.sword.auth import Depositor
from submit_ce.sword.tests.client import ATOM_ENTRY_TYPE, basic_auth
from submit_ce.sword.tests.wrapper import Contributor, MediaLink, wrapper_entry

ZIP = b"PK\x03\x04 pretend this is a zip"


@pytest.fixture
def compiling_app(sword_app):
    """The SWORD app with a compile service that actually produces artefacts."""
    sword_app.state.api.compiler = MockCompileMimesisPdf()
    return sword_app


@pytest.fixture
def client(compiling_app):
    from fastapi.testclient import TestClient
    return TestClient(compiling_app, base_url="https://arxiv.org")


@pytest.fixture
def actor(depositor):
    """The user and client the worker acts as: the depositing account."""
    from submit_ce.domain.agent import HttpClient
    record = Depositor(user_id=depositor.user_id, nickname=depositor.nickname,
                       email=depositor.email, license="x", groups=["cs"])
    return (depositor_user(record, ["cs.*"]),
            HttpClient(agent_type="HttpClient", remote_addr="10.0.0.1"))


@pytest.fixture
def deposited(client, depositor):
    """A wrapper deposit, i.e. exactly what `ingest` leaves behind."""
    media = client.post(
        "/sword-app/cs-collection", content=ZIP,
        headers={"Authorization": basic_auth(depositor.nickname,
                                             depositor.password),
                 "Content-Type": "application/zip"})
    assert media.status_code == 201, media.text

    from submit_ce.sword.tests import client as sword_client
    document = wrapper_entry(
        title="A strangely unique title",
        summary="A concise abstract of the important findings herein",
        primary_category="cs.CG",
        author_name="B. Editor",
        contributors=[Contributor("A. Genius", email="genius@example.org")],
        links=[MediaLink(sword_client.edit_media_link(media.content),
                         "application/zip")])

    wrapper = client.post(
        "/sword-app/cs-collection", content=document,
        headers={"Authorization": basic_auth(depositor.nickname,
                                             depositor.password),
                 "Content-Type": ATOM_ENTRY_TYPE})
    assert wrapper.status_code == 202, wrapper.text

    import arxiv.db.models as models
    sword_id = sword_client.sword_id(wrapper.content)
    tracking = Session.query(models.Tracking).filter_by(sword_id=sword_id).one()
    return tracking.paper_id.removeprefix("submit/")


@pytest.fixture
def deposited_pdf(client, depositor):
    """A deposit whose media is a PDF, so InstallPdfPreview has something to find."""
    from submit_ce.sword.tests import client as sword_client

    media = client.post(
        "/sword-app/cs-collection", content=b"%PDF-1.4\n%%EOF\n",
        headers={"Authorization": basic_auth(depositor.nickname,
                                             depositor.password),
                 "Content-Type": "application/pdf"})
    assert media.status_code == 201, media.text

    document = wrapper_entry(
        title="A strangely unique title",
        summary="A concise abstract of the important findings herein",
        primary_category="cs.CG",
        author_name="B. Editor",
        contributors=[Contributor("A. Genius", email="genius@example.org")],
        links=[MediaLink(sword_client.edit_media_link(media.content),
                         "application/pdf")])

    wrapper = client.post(
        "/sword-app/cs-collection", content=document,
        headers={"Authorization": basic_auth(depositor.nickname,
                                             depositor.password),
                 "Content-Type": ATOM_ENTRY_TYPE})
    assert wrapper.status_code == 202, wrapper.text

    import arxiv.db.models as models
    sword_id = sword_client.sword_id(wrapper.content)
    tracking = Session.query(models.Tracking).filter_by(sword_id=sword_id).one()
    return tracking.paper_id.removeprefix("submit/")


def _advance(app, submission_id, actor):
    creator, http_client = actor
    return worker.advance(app.state.api, submission_id,
                          creator=creator, client=http_client)


# --------------------------------------------------------------- the happy path


def test_a_deposit_reaches_finalized(compiling_app, deposited, actor):
    """The gap this closes: ingest stops at 'incomplete', the worker finishes."""
    outcome = _advance(compiling_app, deposited, actor)

    assert outcome.finalized, outcome
    assert outcome.error is None
    assert "preflight" in outcome.steps
    assert "preview" in outcome.steps
    assert "finalized" in outcome.steps


def test_the_source_format_is_recorded(compiling_app, deposited, actor):
    """Finalize requires it, and only preflight can determine it."""
    _advance(compiling_app, deposited, actor)
    submission, _ = compiling_app.state.api.get_with_history(deposited)
    assert submission.source_format == SourceFormat.TEX


def test_the_submission_is_finalized_in_the_database(compiling_app, deposited,
                                                     actor):
    _advance(compiling_app, deposited, actor)
    submission, _ = compiling_app.state.api.get_with_history(deposited)
    assert submission.is_finalized


# ------------------------------------------------------------------ idempotency


def test_a_second_pass_does_nothing(compiling_app, deposited, actor):
    """The loop will see the same submission again until its status changes."""
    first = _advance(compiling_app, deposited, actor)
    assert first.finalized

    second = _advance(compiling_app, deposited, actor)
    assert second.finalized
    assert second.steps == [], "re-did work on an already finished submission"


def test_preflight_is_not_rerun(compiling_app, deposited, actor):
    """Guarded on the stored artefact, so a restart does not recompile."""
    _advance(compiling_app, deposited, actor)
    assert compiling_app.state.api.get_file_store().does_preflight_exist(deposited)

    outcome = _advance(compiling_app, deposited, actor)
    assert "preflight" not in outcome.steps


# ---------------------------------------------------------------------- resuming


def test_a_partly_processed_submission_resumes(compiling_app, deposited, actor):
    """A worker killed mid-ladder leaves no marker; the next pass continues.

    Preflight is run on its own first, standing in for a process that died before
    compiling.
    """
    api = compiling_app.state.api
    creator, http_client = actor
    assert worker._run_preflight(api, deposited, creator, http_client)

    outcome = _advance(compiling_app, deposited, actor)
    assert outcome.finalized
    assert "preflight" not in outcome.steps, "should not have re-run preflight"
    assert "finalized" in outcome.steps


# ------------------------------------------------------------------- dead ends


def test_no_source_format_stops_without_finalizing(compiling_app, deposited,
                                                   actor, monkeypatch):
    """Preflight that detects nothing usable is a dead end, not a retry loop."""
    monkeypatch.setattr(
        "submit_ce.implementations.compile.directive_manager."
        "DirectiveManager.get_lang_from_preflight",
        staticmethod(lambda data: None))

    outcome = _advance(compiling_app, deposited, actor)
    assert not outcome.finalized
    assert "no usable source format" in outcome.error

    submission, _ = compiling_app.state.api.get_with_history(deposited)
    assert not submission.is_finalized


def test_a_failed_compile_is_not_retried(compiling_app, deposited, actor,
                                         monkeypatch):
    """A compile that leaves no preview must not be attempted again every pass.

    Recompiling identical source fails identically; the submitter sees the log and
    retries deliberately. Mirrors `conditions.has_compiled_current_source`, which
    the Process page uses for the same reason.
    """
    store = compiling_app.state.api.get_file_store()
    monkeypatch.setattr(type(store), "does_preview_exist",
                        lambda self, sid: False)

    first = _advance(compiling_app, deposited, actor)
    assert "preview" in first.steps
    assert not first.finalized, "finalized a submission with no PDF to announce"
    assert "nothing to announce" in first.error

    second = _advance(compiling_app, deposited, actor)
    assert "preview" not in second.steps, "recompiled source that already failed"
    assert not second.finalized


def test_an_error_keeps_the_steps_that_succeeded(compiling_app, deposited,
                                                 actor, monkeypatch):
    """Partial progress is durable: the ladder is not transactional as a whole."""
    monkeypatch.setattr(
        "submit_ce.implementations.compile.directive_manager."
        "DirectiveManager.get_lang_from_preflight",
        staticmethod(lambda data: None))

    outcome = _advance(compiling_app, deposited, actor)
    assert outcome.steps == ["preflight"]
    assert compiling_app.state.api.get_file_store().does_preflight_exist(deposited)


# -------------------------------------------------------------------- shortcuts


def test_an_already_finalized_submission_is_left_alone(compiling_app, deposited,
                                                       actor):
    _advance(compiling_app, deposited, actor)
    outcome = _advance(compiling_app, deposited, actor)
    assert outcome.finalized
    assert outcome.steps == []


def test_outcome_reads_as_a_log_line(compiling_app, deposited, actor):
    """The loop prints these; they should be legible without unpacking."""
    outcome = _advance(compiling_app, deposited, actor)
    assert str(outcome).startswith(f"submission {deposited}: ")
    assert "finalized" in str(outcome)


# ------------------------------------------------------------------- the loop


def test_a_fresh_deposit_is_a_candidate(compiling_app, deposited):
    from submit_ce.sword.worker_loop import candidates
    assert int(deposited) in candidates(Session)


def test_a_finalized_deposit_is_no_longer_a_candidate(compiling_app, deposited,
                                                      actor):
    """What takes a submission out of the set: FinalizeSubmission moves status
    off WORKING."""
    from submit_ce.sword.worker_loop import candidates
    _advance(compiling_app, deposited, actor)
    Session.expire_all()
    assert int(deposited) not in candidates(Session)


def test_a_submission_without_a_sword_id_is_never_picked_up(compiling_app,
                                                            deposited):
    """``sword_id`` is the discriminator.

    A submission created through the web UI has none, and has its own path through
    preflight and compile -- driving it from here would fight the submitter.
    Rather than hand-building a legacy row (a dozen NOT NULL columns with no
    sqlite defaults), this clears the flag on a real one, which is the same
    predicate the query tests.
    """
    import arxiv.db.models as models
    from submit_ce.sword.worker_loop import candidates

    assert int(deposited) in candidates(Session)

    row = Session.get(models.Submission, int(deposited))
    row.sword_id = None
    Session.commit()
    Session.expire_all()

    assert int(deposited) not in candidates(Session)


def test_candidates_are_oldest_first(compiling_app, deposited):
    """A backlog drains in arrival order rather than starving the earliest."""
    from submit_ce.sword.worker_loop import candidates
    found = candidates(Session)
    assert found == sorted(found)


def test_limit_caps_a_pass(compiling_app, deposited):
    from submit_ce.sword.worker_loop import candidates
    assert len(candidates(Session, limit=0)) == 0


def test_run_once_finalizes_the_backlog(compiling_app, deposited):
    """End to end through the loop, with the actor it builds itself."""
    from submit_ce.sword.worker_loop import run_once
    outcomes = run_once(compiling_app.state.api, Session)

    assert [o.submission_id for o in outcomes] == [int(deposited)]
    assert outcomes[0].finalized, outcomes[0]


def test_one_bad_submission_does_not_stop_the_batch(compiling_app, deposited,
                                                    monkeypatch):
    """A failure is logged and the pass continues; the next pass retries it."""
    from submit_ce.sword import worker_loop

    # run_once claims one at a time, so the stub hands back a single id per call
    # and honours `exclude` the way the real query does.
    queue = [999999, int(deposited)]

    def one_at_a_time(session, limit=None, exclude=None):
        remaining = [i for i in queue if i not in (exclude or set())]
        return remaining[:1]

    monkeypatch.setattr(worker_loop, "candidates", one_at_a_time)
    outcomes = worker_loop.run_once(compiling_app.state.api, Session)

    assert [o.submission_id for o in outcomes] == [int(deposited)], \
        "the bad id stopped the pass"
    assert outcomes[0].finalized


# ---------------------------------------------------------------- other formats


def _force_format(monkeypatch, value):
    """Make preflight report a given source format."""
    monkeypatch.setattr(
        "submit_ce.implementations.compile.directive_manager."
        "DirectiveManager.get_lang_from_preflight",
        staticmethod(lambda data: value))


def test_pdf_source_is_installed_not_compiled(compiling_app, deposited_pdf,
                                              actor, monkeypatch):
    """PDF-only needs no tex2pdf round trip; the file is the preview.

    Asserts the submission actually finalizes rather than that the event was
    attempted -- `InstallPdfPreview` requires exactly one PDF in the workspace, so
    an attempt against a zip deposit fails and would otherwise pass this silently.
    """
    _force_format(monkeypatch, SourceFormat.PDF.value)

    outcome = _advance(compiling_app, deposited_pdf, actor)
    assert outcome.finalized, outcome
    assert "preview" in outcome.steps


def test_a_non_processing_format_needs_no_preview(compiling_app, deposited,
                                                  actor, monkeypatch):
    """HTML and friends are their own preview, so the preview gate must not
    block them."""
    _force_format(monkeypatch, SourceFormat.HTML.value)
    store = compiling_app.state.api.get_file_store()
    monkeypatch.setattr(type(store), "does_preview_exist",
                        lambda self, sid: False)

    outcome = _advance(compiling_app, deposited, actor)
    assert outcome.finalized, outcome
    assert "preview" not in outcome.steps


# ------------------------------------------------------------- preflight blob


def test_missing_preflight_blob_reads_as_none(compiling_app, deposited):
    """`get_preflight` answers with a FileDoesNotExist rather than raising."""
    assert worker._preflight_data(compiling_app.state.api, deposited) is None


def test_unreadable_preflight_blob_reads_as_none(compiling_app, deposited,
                                                 actor, monkeypatch):
    """Corrupt JSON is treated as 'no answer', not a crash."""
    creator, http_client = actor
    worker._run_preflight(compiling_app.state.api, deposited, creator, http_client)

    class _Garbage:
        def download_as_text(self):
            return "{not json"

    store = compiling_app.state.api.get_file_store()
    monkeypatch.setattr(type(store), "get_preflight",
                        lambda self, submission_id: _Garbage())
    assert worker._preflight_data(compiling_app.state.api, deposited) is None


# ------------------------------------------------------------------ empty pass


def test_a_pass_with_nothing_waiting_is_quiet(compiling_app, sword_db):
    from submit_ce.sword.worker_loop import run_once
    assert run_once(compiling_app.state.api, Session) == []


def test_main_runs_a_single_pass_by_default(compiling_app, monkeypatch):
    """The Cloud Run Job entrypoint: one pass, exit 0."""
    from submit_ce.sword import worker_loop

    calls = []
    monkeypatch.setattr(worker_loop, "run_once",
                        lambda api, session, limit: calls.append(limit))
    monkeypatch.setattr("submit_ce.implementations.wiring.config_backend_api",
                        lambda settings, impl=None: compiling_app.state.api)

    assert worker_loop.main([]) == 0
    assert calls == [None]


def test_an_existing_preview_is_reused(compiling_app, deposited, actor):
    """The compile is skipped when a usable preview is already there."""
    first = _advance(compiling_app, deposited, actor)
    assert "preview" in first.steps
    assert compiling_app.state.api.get_file_store().does_preview_exist(deposited)

    creator, http_client = actor
    submission, events = compiling_app.state.api.get_with_history(deposited)
    assert not worker._produce_preview(compiling_app.state.api, submission,
                                       events, creator, http_client)


def test_forever_keeps_polling(compiling_app, monkeypatch):
    """--forever runs repeatedly; a failing pass is logged, not fatal."""
    from submit_ce.sword import worker_loop

    passes = []

    def flaky(api, session, limit):
        passes.append(len(passes))
        if len(passes) == 1:
            raise RuntimeError("transient")

    def stop_after_two(_seconds):
        if len(passes) >= 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(worker_loop, "run_once", flaky)
    monkeypatch.setattr(worker_loop.time, "sleep", stop_after_two)
    monkeypatch.setattr("submit_ce.implementations.wiring.config_backend_api",
                        lambda settings, impl=None: compiling_app.state.api)

    with pytest.raises(KeyboardInterrupt):
        worker_loop.main(["--forever", "--interval", "0"])
    assert len(passes) == 2, "a failing pass stopped the loop"


# --------------------------------------------------------------- claiming rows


def test_the_candidate_query_takes_a_skip_locked_lock():
    """Compiled against MySQL, because that is where it has to hold.

    SQLAlchemy's SQLite dialect omits the clause silently, so asserting on the
    sqlite rendering would pass no matter what the code asked for.
    """
    from sqlalchemy import select
    from sqlalchemy.dialects import mysql
    import arxiv.db.models as models
    from submit_ce.sword.worker_loop import WORKING

    stmt = (select(models.Submission.submission_id)
            .where(models.Submission.sword_id.isnot(None),
                   models.Submission.status == WORKING)
            .with_for_update(skip_locked=True))
    assert "FOR UPDATE SKIP LOCKED" in str(stmt.compile(dialect=mysql.dialect()))


def test_sqlite_drops_the_clause_so_tests_never_exercise_locking():
    """Pins the caveat: nothing here proves the locking works.

    If SQLAlchemy's SQLite dialect ever starts rendering FOR UPDATE, this fails and
    the claim in `candidates`' docstring needs revisiting.
    """
    from sqlalchemy import select
    from sqlalchemy.dialects import sqlite
    import arxiv.db.models as models

    stmt = (select(models.Submission.submission_id)
            .with_for_update(skip_locked=True))
    assert "FOR UPDATE" not in str(stmt.compile(dialect=sqlite.dialect()))


def test_exclude_removes_a_submission_from_the_candidate_set(compiling_app,
                                                             deposited):
    from submit_ce.sword.worker_loop import candidates
    assert int(deposited) in candidates(Session)
    assert int(deposited) not in candidates(Session, exclude={int(deposited)})


def test_a_permanent_failure_is_recorded_and_stops_being_a_candidate(
        compiling_app, deposited, actor, monkeypatch):
    """A dead end must not be retried every pass forever.

    Before this, a submission that stopped short stayed a candidate, so the loop
    picked it up every minute and failed identically -- against tex2pdf, in the
    case of a rejected source.
    """
    import arxiv.db.models as models
    from submit_ce.sword import worker_loop

    _force_format(monkeypatch, None)      # dead end: no usable source format
    outcomes = worker_loop.run_once(compiling_app.state.api, Session)

    assert len(outcomes) == 1
    assert outcomes[0].permanent
    Session.expire_all()

    assert int(deposited) not in worker_loop.candidates(Session)
    row = Session.query(models.Tracking).filter(
        models.Tracking.submission_errors.isnot(None)).one()
    assert "no usable source format" in row.submission_errors


def test_a_transient_failure_stays_a_candidate(compiling_app, deposited,
                                               monkeypatch):
    """A 5xx is the compile service's problem, not the source's -- retry it."""
    import httpx

    from submit_ce.sword import worker, worker_loop

    def explode(*args, **kwargs):
        request = httpx.Request("POST", "https://tex2pdf.example/preflight")
        raise httpx.HTTPStatusError(
            "boom", request=request,
            response=httpx.Response(503, text="overloaded", request=request))

    monkeypatch.setattr(worker, "_run_preflight", explode)
    outcomes = worker_loop.run_once(compiling_app.state.api, Session)

    assert len(outcomes) == 1
    assert not outcomes[0].permanent
    assert "503" in outcomes[0].error
    Session.expire_all()
    assert int(deposited) in worker_loop.candidates(Session), \
        "a transient failure took the submission out of the queue"


def test_an_unreachable_service_stays_a_candidate(compiling_app, deposited,
                                                  monkeypatch):
    """Never got an answer at all: DNS, reset, timeout."""
    import httpx

    from submit_ce.sword import worker, worker_loop

    def explode(*args, **kwargs):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(worker, "_run_preflight", explode)
    outcomes = worker_loop.run_once(compiling_app.state.api, Session)

    assert not outcomes[0].permanent
    assert "could not reach" in outcomes[0].error
    Session.expire_all()
    assert int(deposited) in worker_loop.candidates(Session)


@pytest.mark.parametrize("status,permanent", [
    (422, True),    # "ZZRM missing or underspecified" -- the source is the problem
    (400, True),
    (404, True),
    (401, False),   # our credentials, not the deposit
    (403, False),   # expired ADC would otherwise sideline a good submission
    (429, False),   # an explicit "try again"
    (500, False),   # theirs to fix
    (503, False),
])
def test_http_status_decides_whether_to_retry(compiling_app, deposited, actor,
                                              monkeypatch, status, permanent):
    import httpx

    from submit_ce.sword import worker

    def explode(*args, **kwargs):
        request = httpx.Request("POST", "https://tex2pdf.example/convert")
        raise httpx.HTTPStatusError(
            "x", request=request,
            response=httpx.Response(status, text="detail", request=request))

    monkeypatch.setattr(worker, "_run_preflight", explode)
    outcome = _advance(compiling_app, deposited, actor)

    assert outcome.permanent is permanent
    assert str(status) in outcome.error


def test_a_recorded_failure_is_visible_to_the_depositor(compiling_app, deposited,
                                                        actor, monkeypatch,
                                                        client):
    """The point of using arXiv_tracking: /resolve/app/<id> shows it."""
    from submit_ce.sword import worker_loop

    _force_format(monkeypatch, None)
    worker_loop.run_once(compiling_app.state.api, Session)
    Session.expire_all()

    import arxiv.db.models as models
    sword_id = Session.get(models.Submission, int(deposited)).sword_id
    response = client.get(f"/resolve/app/{sword_id}")
    assert response.status_code == 200


def test_run_once_claims_one_at_a_time(compiling_app, deposited, monkeypatch):
    """Selecting a batch would drop every lock at the first save."""
    from submit_ce.sword import worker_loop

    limits = []
    real = worker_loop.candidates

    def record(session, limit=None, exclude=None):
        limits.append(limit)
        return real(session, limit=limit, exclude=exclude)

    monkeypatch.setattr(worker_loop, "candidates", record)
    worker_loop.run_once(compiling_app.state.api, Session)

    assert limits and all(value == 1 for value in limits), limits


def test_limit_stops_the_pass_early(compiling_app, deposited, actor):
    """The other way out of the loop: the cap, rather than an empty queue."""
    from submit_ce.sword.worker_loop import run_once
    assert run_once(compiling_app.state.api, Session, limit=0) == []
    # Untouched, so a later pass still has it.
    from submit_ce.sword.worker_loop import candidates
    assert int(deposited) in candidates(Session)


# ------------------------------------------------- the apps must not run a worker


def _imported_modules(module) -> set:
    """Module names a source file imports, by parsing it rather than grepping.

    A substring search over the source would match the word in a comment or a
    docstring, which is how a test like this quietly stops meaning anything.
    """
    import ast
    names = set()
    for node in ast.walk(ast.parse(open(module.__file__).read())):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


def test_creating_the_sword_app_starts_no_thread(sword_db):
    """The API scales to many instances; a worker in each would fight the others.

    There is no lease, so concurrent workers can duplicate a compile. Keeping the
    worker out of the app is what makes "one worker" a deployment choice rather
    than something that silently stops being true when the API scales up.
    """
    import threading

    from submit_ce.sword.app import create_sword_app

    before = threading.active_count()
    create_sword_app()
    assert threading.active_count() == before, "app startup spawned a thread"


def test_neither_app_imports_the_worker():
    import submit_ce.sword.app as sword_app_module
    import submit_ce.ui.factory as flask_factory

    for module in (sword_app_module, flask_factory):
        imported = _imported_modules(module)
        assert not any("worker" in name for name in imported), \
            f"{module.__name__} imports the worker: {sorted(imported)}"


def test_the_worker_is_reachable_as_a_module_entrypoint():
    """`python -m submit_ce.sword.worker_loop` is how the Job will run it."""
    import importlib.util
    assert importlib.util.find_spec("submit_ce.sword.worker_loop") is not None


# ------------------------------------------------------- 00README and edge cases


def test_a_deposited_zzrm_becomes_user_decisions(compiling_app, deposited,
                                                 monkeypatch):
    """A depositor can ship 00README.json to pick the top-level file and compiler.

    That is the SWORD stand-in for the choices the review form collects, so the
    worker feeds it into SetDirectivesAndCleanup the way the UI does.
    """
    class _Blob:
        def download_as_text(self):
            return '{"process": {"compiler": "pdflatex"}}'

    store = compiling_app.state.api.get_file_store()
    monkeypatch.setattr(type(store), "get_source_file",
                        lambda self, submission_id, path: _Blob())
    monkeypatch.setattr(
        "submit_ce.implementations.compile.directive_manager."
        "DirectiveManager.convert_zzrm_to_user_decisions",
        staticmethod(lambda raw: {"converted": raw}))

    assert worker._zzrm_decisions(compiling_app.state.api, deposited) == \
        {"converted": {"process": {"compiler": "pdflatex"}}}


def test_a_corrupt_zzrm_is_ignored(compiling_app, deposited, monkeypatch):
    """Bad JSON in a depositor's zip must not stop the whole deposit."""
    class _Blob:
        def download_as_text(self):
            return "{not json"

    store = compiling_app.state.api.get_file_store()
    monkeypatch.setattr(type(store), "get_source_file",
                        lambda self, submission_id, path: _Blob())
    assert worker._zzrm_decisions(compiling_app.state.api, deposited) is None


def test_no_zzrm_is_the_normal_case(compiling_app, deposited):
    assert worker._zzrm_decisions(compiling_app.state.api, deposited) is None


def test_an_unreadable_error_body_does_not_mask_the_failure(compiling_app):
    """The excerpt is for humans; failing to read it must not raise."""
    class _Exploding:
        @property
        def text(self):
            raise RuntimeError("stream consumed")

    assert worker._body(_Exploding()) == "<unreadable>"


def test_error_bodies_are_trimmed_to_one_line():
    class _Chatty:
        text = "  a\n\n  very   long\n" + ("x" * 500)

    body = worker._body(_Chatty())
    assert "\n" not in body and len(body) <= 200


def test_outcome_labels_a_retryable_failure_distinctly():
    retryable = worker.Outcome(1, ["preflight"], False, error="503", permanent=False)
    permanent = worker.Outcome(1, ["preflight"], False, error="422", permanent=True)
    assert "retryable" in str(retryable)
    assert "PERMANENT" in str(permanent)


def test_recording_a_failure_without_a_tracking_row_is_survivable(compiling_app,
                                                                  sword_db):
    """A submission with no tracking row should log, not raise."""
    from submit_ce.sword.worker_loop import record_failure
    record_failure(Session, 999999, "nothing to attach this to")


# --------------------------------------------------- the ZZRM the compiler needs


def _zzrm_written(saved):
    return [e for e in saved if type(e).__name__ == "StoreZzrm"]


@pytest.fixture
def recording_save(compiling_app, monkeypatch):
    """Capture the events the ladder saves, while still saving them."""
    saved = []
    original = type(compiling_app.state.api).save

    def record(self, *events, **kwargs):
        saved.extend(events)
        return original(self, *events, **kwargs)

    monkeypatch.setattr(type(compiling_app.state.api), "save", record)
    return saved


def test_a_zzrm_is_written_even_when_the_depositor_shipped_one(
        compiling_app, deposited, actor, recording_save, monkeypatch):
    """SetDirectivesAndCleanup *deletes* the depositor's 00README.json.

    It converts it to user_decisions.json first, so the choices survive -- but the
    file tex2pdf reads is gone. Skipping StoreZzrm when the depositor supplied one
    therefore leaves no ZZRM at all, and /convert answers
    "ZZRM missing or underspecified".
    """
    class _Blob:
        def download_as_text(self):
            return '{"sources": [{"filename": "main.tex", "usage": "toplevel"}]}'

    store = compiling_app.state.api.get_file_store()
    monkeypatch.setattr(type(store), "get_source_file",
                        lambda self, submission_id, path: _Blob())

    _advance(compiling_app, deposited, actor)
    assert _zzrm_written(recording_save), \
        "no ZZRM stored; the depositor's copy is deleted by cleanup"


def test_the_stored_zzrm_names_a_texlive_version(compiling_app, deposited,
                                                 actor, recording_save):
    """Without it the file is 'underspecified' and the compile is refused."""
    _advance(compiling_app, deposited, actor)
    stored = _zzrm_written(recording_save)
    assert stored, "no ZZRM stored"
    assert stored[-1].zzrm.get("texlive_version"), stored[-1].zzrm


def test_depositor_choices_survive_into_the_stored_zzrm(compiling_app, deposited,
                                                        actor, recording_save,
                                                        monkeypatch):
    """A depositor picking pdflatex must not have it overwritten."""
    monkeypatch.setattr(
        "submit_ce.implementations.compile.directive_manager."
        "DirectiveManager.convert_zzrm_to_user_decisions",
        staticmethod(lambda raw: {"process": {"compiler": "pdflatex"},
                                  "sources": [{"filename": "main.tex"}]}))

    class _Blob:
        def download_as_text(self):
            return '{"process": {"compiler": "pdflatex"}}'

    store = compiling_app.state.api.get_file_store()
    monkeypatch.setattr(type(store), "get_source_file",
                        lambda self, submission_id, path: _Blob())

    _advance(compiling_app, deposited, actor)
    stored = _zzrm_written(recording_save)
    assert stored[-1].zzrm["process"]["compiler"] == "pdflatex"


def test_a_complete_zzrm_is_not_rewritten(compiling_app, deposited, monkeypatch):
    """Rewriting invalidates the source package, which would force a re-preflight."""
    class _Complete:
        def download_as_text(self):
            return '{"texlive_version": "2025"}'

    store = compiling_app.state.api.get_file_store()
    monkeypatch.setattr(type(store), "get_source_file",
                        lambda self, submission_id, path: _Complete())
    assert worker._has_usable_zzrm(compiling_app.state.api, deposited)


def test_an_incomplete_zzrm_counts_as_missing(compiling_app, deposited,
                                              monkeypatch):
    class _NoVersion:
        def download_as_text(self):
            return '{"sources": [{"filename": "main.tex"}]}'

    store = compiling_app.state.api.get_file_store()
    monkeypatch.setattr(type(store), "get_source_file",
                        lambda self, submission_id, path: _NoVersion())
    assert not worker._has_usable_zzrm(compiling_app.state.api, deposited)


def test_a_corrupt_zzrm_counts_as_missing(compiling_app, deposited, monkeypatch):
    class _Corrupt:
        def download_as_text(self):
            return "{not json"

    store = compiling_app.state.api.get_file_store()
    monkeypatch.setattr(type(store), "get_source_file",
                        lambda self, submission_id, path: _Corrupt())
    assert not worker._has_usable_zzrm(compiling_app.state.api, deposited)


def test_user_decisions_are_read_on_a_resumed_pass(compiling_app, deposited,
                                                   monkeypatch):
    """After cleanup the source 00README is gone; user_decisions.json remains."""
    class _Decisions:
        def download_as_text(self):
            return '{"texlive_version": "2023"}'

    store = compiling_app.state.api.get_file_store()
    monkeypatch.setattr(type(store), "get_user_decisions",
                        lambda self, submission_id: _Decisions())
    assert worker._user_decisions(compiling_app.state.api, deposited) == \
        {"texlive_version": "2023"}


def test_unreadable_user_decisions_are_ignored(compiling_app, deposited,
                                               monkeypatch):
    class _Corrupt:
        def download_as_text(self):
            return "{not json"

    store = compiling_app.state.api.get_file_store()
    monkeypatch.setattr(type(store), "get_user_decisions",
                        lambda self, submission_id: _Corrupt())
    assert worker._user_decisions(compiling_app.state.api, deposited) is None


def test_missing_preflight_blocks_the_zzrm(compiling_app, deposited, actor,
                                           monkeypatch):
    """Without preflight there is nothing to build the ZZRM from.

    Reachable on a resumed pass if gcp_preflight.json has gone away: the source
    format is already recorded, so the preflight step is skipped, but the ZZRM
    still needs preflight's answers.
    """
    from submit_ce.domain.exceptions import InvalidEvent

    monkeypatch.setattr(worker, "_preflight_data", lambda api, sid: None)
    monkeypatch.setattr(worker, "_has_usable_zzrm", lambda api, sid: False)

    class _Sub:
        submission_id = int(deposited)
        source_format = SourceFormat.TEX

    creator, http_client = actor
    with pytest.raises(InvalidEvent, match="no preflight data"):
        worker._make_directives(compiling_app.state.api, _Sub(), creator,
                                http_client)


def test_an_existing_complete_zzrm_short_circuits_the_step(compiling_app,
                                                           deposited, actor,
                                                           recording_save,
                                                           monkeypatch):
    """Nothing to do: directives present and the ZZRM already usable."""
    store = compiling_app.state.api.get_file_store()
    monkeypatch.setattr(type(store), "does_directives_exist",
                        lambda self, sid: True)
    monkeypatch.setattr(worker, "_has_usable_zzrm", lambda api, sid: True)

    class _Sub:
        submission_id = int(deposited)
        source_format = SourceFormat.TEX

    creator, http_client = actor
    assert not worker._make_directives(compiling_app.state.api, _Sub(),
                                       creator, http_client)
    assert not _zzrm_written(recording_save)


def test_a_depositor_texlive_version_is_not_overwritten(compiling_app, deposited,
                                                        actor, recording_save,
                                                        monkeypatch):
    """The default only fills a gap; an explicit choice wins."""
    monkeypatch.setattr(
        "submit_ce.implementations.compile.directive_manager."
        "DirectiveManager.convert_zzrm_to_user_decisions",
        staticmethod(lambda raw: {"texlive_version": "2023"}))

    class _Blob:
        def download_as_text(self):
            return '{"texlive_version": "2023"}'

    store = compiling_app.state.api.get_file_store()
    # Present but not usable, so the step runs and seeds from the decisions.
    monkeypatch.setattr(type(store), "get_source_file",
                        lambda self, submission_id, path: _Blob())
    monkeypatch.setattr(worker, "_has_usable_zzrm", lambda api, sid: False)

    _advance(compiling_app, deposited, actor)
    stored = _zzrm_written(recording_save)
    assert stored, "no ZZRM stored"
    assert str(stored[-1].zzrm["texlive_version"]) == "2023", stored[-1].zzrm


# --------------------------------------------------------- replacements compile


@pytest.fixture
def media_href(client, depositor):
    """A staged media deposit, for a replacement wrapper to reference."""
    from submit_ce.sword.tests import client as sword_client

    response = client.post(
        "/sword-app/cs-collection", content=ZIP,
        headers={"Authorization": basic_auth(depositor.nickname,
                                             depositor.password),
                 "Content-Type": "application/zip"})
    assert response.status_code == 201
    return sword_client.edit_media_link(response.content)


@pytest.fixture
def announced_deposit(compiling_app, deposited, actor, depositor):
    """A finalized deposit, faked into an announced paper so it can be replaced.

    Returns (paper_id, original submission id).
    """
    from datetime import datetime, timezone

    import arxiv.db.models as models

    _advance(compiling_app, deposited, actor)
    paper_id = "2699.00001"

    document = models.Document(paper_id=paper_id,
                               title="A strangely unique title",
                               submitter_email="genius@example.org")
    Session.add(document)
    Session.flush()

    row = Session.get(models.Submission, int(deposited))
    row.status = 7
    row.doc_paper_id = paper_id
    row.document_id = document.document_id
    Session.add(models.PaperOwner(
        document_id=document.document_id, user_id=depositor.user_id,
        date=datetime.now(timezone.utc), valid=1, flag_author=1, flag_auto=0))
    Session.query(models.Tracking).filter_by(
        paper_id=f"submit/{deposited}").update({"paper_id": paper_id})
    Session.commit()
    return paper_id, int(deposited)


def _replace(client, depositor, paper_id, media_href):
    from submit_ce.sword.tests.test_replace import _auth, _wrapper

    return client.put(f"/sword-app/edit/{paper_id}", content=_wrapper(media_href),
                      headers={**_auth(depositor),
                               "Content-Type": ATOM_ENTRY_TYPE})


def _version_row(paper_id, version):
    import arxiv.db.models as models

    return Session.query(models.Submission).filter_by(
        doc_paper_id=paper_id, version=version).one()


def test_a_replacement_is_compiled_and_finalized(compiling_app, depositor,
                                                 announced_deposit, media_href,
                                                 client):
    """The end of the chain the sword_id and _load changes exist for.

    Files, preview and event log all live under the paper's original id, while the
    replacement is a separate classic row. The worker finds the row and drives the
    paper -- driving the row would compile an empty workspace.
    """
    from submit_ce.sword.worker_loop import run_once

    paper_id, _origin = announced_deposit
    assert _replace(client, depositor, paper_id, media_href).status_code == 202
    Session.expire_all()

    outcomes = run_once(compiling_app.state.api, Session)
    assert outcomes, "the worker found no replacement to process"
    assert outcomes[0].finalized, outcomes[0]

    Session.expire_all()
    assert _version_row(paper_id, 2).status == 1, \
        "the version row was not moved to SUBMITTED"


def test_the_worker_drives_the_paper_not_the_row(compiling_app, depositor,
                                                 announced_deposit, media_href,
                                                 client):
    """A replacement row's workspace is empty; the paper's is not."""
    from submit_ce.sword.worker_loop import domain_id

    paper_id, origin = announced_deposit
    _replace(client, depositor, paper_id, media_href)
    Session.expire_all()

    assert domain_id(Session, _version_row(paper_id, 2).submission_id) == origin
    assert domain_id(Session, origin) == origin


def test_a_replaced_paper_reads_as_its_newest_version(compiling_app, depositor,
                                                      announced_deposit,
                                                      media_href, client):
    """Loading by the original id must not report the state it had at v1."""
    paper_id, origin = announced_deposit

    submission, _ = compiling_app.state.api.get_with_history(str(origin))
    assert submission.version == 1

    _replace(client, depositor, paper_id, media_href)
    Session.expire_all()

    submission, _ = compiling_app.state.api.get_with_history(str(origin))
    assert submission.version == 2, "still reporting the version it replaced"
    assert submission.submission_id == str(origin), "identity changed with version"
