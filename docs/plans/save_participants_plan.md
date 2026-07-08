# SaveParticipant: transaction-phase callbacks for SubmitApi.save()

## Context

`SubmitApi.save()` runs a critical section (row lock → validate/execute events → persist → commit) that is currently a private detail of `LegacySubmitImplementation`. Composed implementations like `PubsubEventSubmitImplementation` can only act before/after the whole `save()` call — nothing can run *inside* the transaction (atomic audit/outbox writes, global invariant checks under the lock) and nothing is notified of rollback (relevant for the fs/db desync problem documented in `legacy_implementation/__init__.py:156-178`).

This change adds a **SaveParticipant** abstraction: objects enlisted in the save transaction with four phase callbacks (`under_lock`, `before_commit`, `after_commit`, `on_rollback`), injected via constructor. `on_rollback` receives an explicit `SaveFailure` record (exception + `SavePhase` enum + current event/participant) built from a cursor the save loop maintains, so participants never reverse-engineer failure location from exception types.

Scope decision (user-confirmed): **core machinery + tests only**. Pubsub stays a decorator; conversion is a follow-up.

## New file: `submit_ce/api/save_participant.py`

Follows codebase style: ABC with no-op defaults (like `EventWithSideEffect.validate_under_lock` in `domain/event/base.py:250`), `(str, Enum)` for the enum (like `SubmissionType` in `domain/submission.py:245`). Use `TYPE_CHECKING` import for `SubmitApi` to avoid a circular import with `api/submit.py`.

```python
class SavePhase(str, Enum):
    LOAD_LOCK = "load_lock"                                  # _load(..., lock_row=True)
    PARTICIPANT_UNDER_LOCK = "participant_under_lock"
    EVENT_VALIDATE_UNDER_LOCK = "event_validate_under_lock"
    EVENT_EXECUTE = "event_execute"                          # side effects; not rolled back by db
    EVENT_APPLY = "event_apply"
    EVENT_PERSIST = "event_persist"                          # db.store_event / store_withdrawal
    PARTICIPANT_BEFORE_COMMIT = "participant_before_commit"
    COMMIT = "commit"                                        # session.commit() itself → indeterminate state

@dataclass
class SaveContext:
    api: "SubmitApi"
    submission_id: Optional[str]
    requested_events: Sequence[Event]
    before: Optional[Submission] = None          # set once loaded under lock
    existing_events: List[Event] = field(default_factory=list)
    after: Optional[Submission] = None           # set as events apply
    committed: List[Event] = field(default_factory=list)   # includes consequence events
    # cursor — updated by the save loop just before each risky call
    phase: SavePhase = SavePhase.LOAD_LOCK
    current_event: Optional[Event] = None
    current_participant: Optional["SaveParticipant"] = None

@dataclass(frozen=True)
class SaveFailure:
    exc: BaseException
    phase: SavePhase
    event: Optional[Event] = None
    participant: Optional["SaveParticipant"] = None

class SaveParticipant(ABC):     # all methods no-op defaults; docstrings define the contract
    def under_lock(self, ctx: SaveContext) -> None: ...      # raise → clean abort
    def before_commit(self, ctx: SaveContext) -> None: ...   # raise → rollback (executed side effects survive)
    def after_commit(self, ctx: SaveContext) -> None: ...    # exceptions logged & swallowed
    def on_rollback(self, ctx: SaveContext, failure: SaveFailure) -> None: ...  # never raises (logged)
```

Contract points to document in docstrings:
- Ordering: list order for `under_lock`/`before_commit`; **reverse** list order for `after_commit`/`on_rollback` (onion semantics).
- `on_rollback` fires only on actual rollback — NOT for `after_commit` failures.
- `phase == COMMIT` failure means indeterminate DB state (alert, don't compensate).
- `event.executed` set → side effects definitely ran; `phase == EVENT_EXECUTE` → that event's side effects in unknown partial state.
- No transaction handle is exposed on `SaveContext` (deliberately deferred until a use case needs it, e.g. an outbox participant); `before_commit` participants observe state and can veto by raising, but cannot yet write in the same transaction.

Re-export from `submit_ce/api/__init__.py` alongside the existing exports.

## Modify: `submit_ce/implementations/legacy_implementation/__init__.py`

**`__init__` (line 79):** add `participants: Optional[List[SaveParticipant]] = None` param → `self.participants = list(participants or [])`.

**`save()` (line 133):** restructure both branches (general + Withdraw) to:
1. Build a `SaveContext`.
2. Wrap the critical section in one `try/except BaseException` (single try, no nesting — cursor fields on `ctx` are updated by assignments just before each risky call).
3. General path: `_load(lock_row=True)` sets `ctx.before/existing_events` → fire `under_lock` participants (cursor: `PARTICIPANT_UNDER_LOCK` + participant) → delegate to `_save(ctx=...)`.
4. Except handler: `session.rollback()` explicitly, build `SaveFailure(exc, ctx.phase, ctx.current_event, ctx.current_participant)`, notify `on_rollback` in reverse order (each individually try/excepted with `logger.exception`, never masking), then bare `raise` — the original exception propagates unchanged so existing `except InvalidEvent` handling in controllers is untouched.

**`_save()` (line 185):** takes `ctx`; updates cursor before each step in the queue loop:
- `ctx.current_event = event`; `EVENT_VALIDATE_UNDER_LOCK` before `validate_under_lock` (line 219), `EVENT_EXECUTE` before `execute` (line 221), `EVENT_APPLY` before `apply` (line 226), `EVENT_PERSIST` before `db.store_event` (line 228). Append committed events to `ctx.committed` (keep the local `committed` list behavior; `ctx.committed` can alias it). Set `ctx.after` as `after` advances; clear `ctx.current_event` when the queue drains.
- After the loop: fire `before_commit` participants (reverse order, cursor `PARTICIPANT_BEFORE_COMMIT` + participant), then cursor `COMMIT`, `session.commit()` (line 238).
- After successful commit: fire `after_commit` in reverse order, each wrapped in `try/except Exception: logger.exception(...)` — never fails a committed save.

**`_save_withdrawal()` (line 241):** same treatment so withdrawals don't silently skip participants: `ctx.before = seed` after `load_latest_announced`, fire `under_lock`; cursor `EVENT_PERSIST` around `store_withdrawal`, `EVENT_EXECUTE` around `event.execute`; `before_commit` → `COMMIT` → commit (line 261) → `after_commit`. The shared `try/except`/rollback-notify lives in `save()`, covering this path too.

Note: today rollback is implicit via the `with session:` context manager — the new explicit `session.rollback()` in the except handler is required so `on_rollback` participants observe post-rollback state.

## Modify: `submit_ce/implementations/legacy_implementation/flask_impl.py`

`FlaskSubmitImplementation.__init__`: add `participants=None`, pass through to `super().__init__`.

## Wiring: `submit_ce/ui/backend.py`

No functional change needed (default is empty list). Optionally pass `participants=[]` explicitly at the `FlaskSubmitImplementation(...)` construction (line 40) as the documented injection point — a one-line comment noting this is where participants get wired.

## `NullImplementation` (`submit_ce/implementations/__init__.py:250`)

Leave as-is (its trivial `save()` has no participants). Not part of the transactional contract; pragma no cover already.

## Tests: new `submit_ce/ui/tests/test_save_participants.py`

Mirror the pattern of `test_save_validate_under_lock.py` (app fixture, `sub_created`, throwaway probe classes, `current_app.api`). Inject participants by appending to `current_app.api.participants` (restore in a finally/fixture, since the `app` fixture may be session-scoped) or by constructing a fresh `FlaskSubmitImplementation(store=..., participants=[...])` inside the app context — prefer whichever the existing fixtures make cleanest; direct construction avoids cross-test leakage.

A `_ProbeParticipant(SaveParticipant)` records `(phase_name, participant_id)` tuples into a shared list, with flags to raise in a chosen phase.

Test cases:
1. **Happy-path ordering**: with two participants A, B and one side-effect event, calls are `A.under_lock, B.under_lock, <event validate/execute>, B.before_commit, A.before_commit, B.after_commit, A.after_commit` and event history grows by one.
2. **`under_lock` raise** → nothing committed (history unchanged), event `execute` never ran, `on_rollback` fired in reverse order with `failure.phase == PARTICIPANT_UNDER_LOCK` and `failure.participant is` the raiser; original exception type propagates.
3. **`before_commit` raise** → history unchanged (DB rolled back), `on_rollback` with `phase == PARTICIPANT_BEFORE_COMMIT`; note event `execute` DID run (assert probe event's calls) — documents the side-effect caveat.
4. **Event `validate_under_lock` raise** (reuse `_ProbeSideEffect`-style event) → `on_rollback` with `phase == EVENT_VALIDATE_UNDER_LOCK` and `failure.event is` the probe event; `InvalidEvent` propagates unchanged.
5. **`after_commit` raise** → save returns normally, event committed, `on_rollback` NOT called.
6. **`on_rollback` raise** → other participants' `on_rollback` still called; the original exception (not the participant's) propagates.
7. **`ctx` contents**: in `before_commit`, `ctx.after` is set and `ctx.committed` non-empty.
8. **Withdraw path** (new coverage): a participant fires on `save(Withdraw(...))` — model the setup on the withdraw controller test fixtures if usable (`published_submission` fixture); if setting one up proves heavy, cover at least under_lock/before_commit/after_commit firing.

## Verification

```bash
uv run pytest submit_ce/ui/tests/test_save_participants.py        # new tests
uv run pytest submit_ce/ui/tests/test_save_validate_under_lock.py # existing lock-path behavior unchanged
uv run pytest submit_ce                                           # full suite — save() is on every fixture path
uv run ruff check --output-format=github submit_ce
```

The full suite matters here: every stage fixture (`sub_created` … `published_submission`) goes through `save()`, so any regression in the restructured critical section surfaces broadly.
