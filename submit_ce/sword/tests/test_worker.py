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

    monkeypatch.setattr(worker_loop, "candidates",
                        lambda session, limit=None: [999999, int(deposited)])
    outcomes = worker_loop.run_once(compiling_app.state.api, Session)

    assert [o.submission_id for o in outcomes] == [int(deposited)]
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
