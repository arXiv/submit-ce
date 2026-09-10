# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment Setup

- **Python:** >=3.11,<3.12, managed with `uv`
- **macOS:** `brew install protobuf@21 && pyenv shell 3.11 && uv sync`
- **Linux:** `sudo apt-get install cmake libprotobuf-dev protobuf-compiler default-libmysqlclient-dev && uv sync`
- **GCP creds:** `gcloud auth application-default login` — required, since the file store is a GCS bucket
- **Test database:** `uv run python submit_ce/make_test_db.py bootstrap_db` (creates `legacy.db` SQLite + test users)

`arxiv-base` is pinned to a **git branch**, not a release (see `[tool.uv.sources]` in `pyproject.toml`).
If shared-model behavior looks wrong, check which branch is pinned before assuming the bug is here.

## Common Commands

```bash
# Tests — ./test.sh is canonical; it enumerates the dirs that are meant to run
./test.sh
uv run pytest path/to/test_file.py::TestClass::test_method   # single test
uv run pytest --ignore=submit_ce/implementations/pubsub       # what CI runs (pubsub needs an emulator)

# Lint — ./lint.sh is canonical
./lint.sh    # uv run ruff check --output-format=github submit_ce

# Run the Flask UI on :8000 — use local_ui.py, not a bare `flask run`.
# It sets the GCS / Pub/Sub / LOCAL_LOGIN env vars the app needs.
uv run python local_ui.py       # then open http://localhost:8000/debug/login

# Run the SWORD deposit API (FastAPI) on :8001
uv run python local_sword.py    # then curl -si localhost:8001/status
uv run uvicorn submit_ce.sword.app:create_sword_app --factory --reload --port 8001  # auto-reload
```

Both local runners default `DEV_NAME`/`STORE_GS_PREFIX` to a hardcoded developer name — set it to your own
before uploading, or you will write into someone else's bucket prefix.

`ruff`'s rule set is deliberately narrowed to `["E4", "E7", "E9", "F"]` in `pyproject.toml`. Widening it is
its own change with its own cleanup — don't let a version bump do it. CI runs lint with
`continue-on-error: true`, so a green check does not mean lint passed.

## Architecture

This is the arXiv paper submission system — a replacement for the legacy submission UI. Two front ends run
from **the same image and the same backend**: a **Flask UI** (`submit_ce/ui`) and a **SWORD deposit API**
(`submit_ce/sword`, FastAPI). Cloud Run overrides the entrypoint per service; see `Dockerfile` and `cicd/`.

Note that `submit_ce/api/` is *not* a web service — it is the abstract interface layer both front ends
depend on. (`main.py` still references `submit_ce.fastapi.app:app`, a package that no longer exists. It is
dead; don't use it as an entrypoint.)

### Layer Overview

**`submit_ce/domain/`** — Core data models and event system
- `Submission`, `SubmissionMetadata`, `Author` (in `submission.py`); `Classification`, `License` (in `meta.py`)
- Changes to submissions are expressed as **domain events** (in `domain/event/`) that project onto submission
  state. Key events: `CreateSubmission`, `SetTitle`, `SetAuthors`, `SetPrimaryClassification`,
  `FinalizeSubmission`. `EventWithSideEffect` subclasses (file uploads, email) also act on the outside world.
- Actors are typed in `domain/agent.py`, and the two unions are distinct:
  - `User = PublicUser | StaffUser | System`
  - `Client = HttpClient | InternalClient` — the *tool* making the request, not a user

**`submit_ce/api/`** — Abstract service interfaces
- `SubmitApi` — abstract base for all submission CRUD operations
- `SubmissionFileStore` — abstract file storage (note the name; it is not `FileStore`)
- `CompileService` — abstract PDF compilation interface
- `EmailService` — abstract outbound mail
- `SaveParticipant` / `SaveContext` / `SavePhase` — hooks that run inside every `save()` transaction

**`submit_ce/implementations/`** — Concrete implementations
- `wiring.py` — `config_backend_api()` builds the configured `SubmitApi`. Framework-neutral on purpose
  (imports neither Flask nor FastAPI) so both front ends share it. **New backend wiring goes here.**
- `legacy_implementation/` — main production impl. `LegacySubmitImplementation` persists to the classic
  arXiv MySQL tables via `arxiv.db`; `FlaskSubmitImplementation` and `FastapiSubmitImplementation`
  subclass it and differ only in how they obtain a SQLAlchemy session.
- `file_store/gs_file_store.py` — `GsFileStore`, the Google Cloud Storage backend
- `compile/compile_api_service.py` — calls `tex2pdf-api` at `settings.COMPILE_API_URL`
- `email/` — `HalonEmailService` (real SMTP) and `EmailInMemory` (tests), selected by `EMAIL_MODE`
- `pubsub/` — `PubsubEventSubmitImplementation`, a decorator that publishes on `save()`. **Not currently
  wired into `wiring.py`** — only its own tests construct it. Excluded from CI tests.

**`submit_ce/ui/`** — Flask web application
- `factory.py` — `create_web_app()`; builds the app and calls `config_backend_api()` for the backend
- `config.py` — `Settings`, extending arxiv-base's `Settings`
- `workflow/` — stage definitions and `WorkflowProcessor`, which decides the current stage and what is blocked
- `controllers/` — per-action logic (`new/` for the new-submission stages, plus `cross`, `withdraw`, `jref`, …)
- `routes/ui.py` — the `UI` blueprint; `routes/flow_control.py` handles stage-to-stage redirects
- `backend.py` — request-scoped persistence helpers over `current_app.api`, caching the submission on Flask `g`

**`submit_ce/sword/`** — SWORD v2 deposit API (FastAPI)
- `app.py` — `create_sword_app()`. Read its module docstring before adding endpoints: DB-touching endpoints
  must be `def`, not `async def`, or requests will share one SQLAlchemy session.

### Key Design Patterns

- **Events are the write path.** `save()` validates events, applies them, and persists the result. Reads do
  *not* replay history — `LegacySubmitImplementation._load()` projects a classic `arXiv_submissions` row into
  a `Submission` via `to_submission()`, and returns the stored event list alongside it as history.
- **Pluggable implementations:** `SubmissionFileStore`, `CompileService`, `EmailService`, and `SubmitApi` are
  injected through abstract interfaces, so implementations swap without touching domain or UI code.
- **Workflow stages:** the new-submission order is `VerifyUser → Agreement → License → Classification →
  FileUpload → ReviewFiles → Process → Metadata → FinalPreview`, confirmed by `Confirm`. `ReplacementWorkflow`
  is a shorter variant with every stage `must_see=True`. Both are defined in `ui/workflow/__init__.py`.
- **Row locking on save:** `save()` locks the `arXiv_submissions` row for file-changing events, because DB
  state and file-store state must not diverge. See the long comment in `legacy_implementation/__init__.py`.

### Configuration

`Settings` (`submit_ce/ui/config.py`) is the single source of config for both front ends. Most settings are
**unprefixed** env vars — `STORE`, `STORE_GS_BUCKET`, `QA_GS_BUCKET`, `QA_PUBSUB_ENABLED`, `CLASSIC_DB_URI`,
`COMPILE_API_URL`, `EMAIL_MODE`, `LOCAL_LOGIN`. The `SUBMIT_API_` prefix is narrower than it looks: those vars
are collected into `settings.api_config` for the submit-api *client* only.

`settings` is built at import time, so anything that sets env vars must do so **before** importing
`submit_ce.ui.config` (both local runners are written this way, with the import deliberately placed low).

### External Dependencies

| Service | Purpose | Default |
|---------|---------|---------|
| MySQL (via `arxiv.db`) | Submission persistence | `sqlite:///legacy.db` locally |
| Google Cloud Storage | File storage (`STORE=gs`) | bucket `arxiv-submit-dev` |
| `tex2pdf-api` | PDF compilation | the Cloud Run URL in `COMPILE_API_URL`, **not** localhost |
| Halon SMTP | Outbound email (`EMAIL_MODE=HALON`) | `TESTING` → in-memory, sends nothing |
| GCP Pub/Sub | QA metadata snapshot on finalize | `QA_PUBSUB_ENABLED`, emulator locally |

> **Note (Apr 2026):** File storage supports GCS buckets only — `STORE` accepts `gs` or `null`, and there is
> no local-filesystem store.

> `CompileApiService.is_available()` GETs `COMPILE_API_URL` without the auth header its other methods send,
> so an auth-requiring Cloud Run service answers 403. "Compiler unhealthy" at startup is expected locally and
> does not mean tex2pdf is down.
