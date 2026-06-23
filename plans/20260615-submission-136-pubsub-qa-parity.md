# SUBMISSION-136 — Pub/Sub messages for the submit event (QA 1.5 parity)

Branch: `SUBMISSION-136-pubsub` · Date: 2026-06-15

## Context

SUBMISSION-136 is "pubsub messages for submit event." The current branch already adds a first
cut (`14d364c "Adds pubsub for SubmitApi.save() of Events"`): `PubsubEventSubmitImplementation`
publishes a JSON `EventList` (an array of full domain `Event` objects) to a topic on every
`save()`.

The goal of this work is **QA 1.5 parity** — making sure submit-ce produces the Pub/Sub
messages the arXiv QA pipeline actually relies on. Investigation found these are **two
different mechanisms**, and the decision (confirmed with the human) is to support
**both**:

1. **GCS bucket-notification parity (the part QA needs today).** QA is *not* driven by a
   submission-events topic. It is driven by **object-change notifications on the
   `arxiv-submission` GCS bucket** (`gsutil notification create` → topic
   `projects/arxiv-production/topics/arxiv-submission`, per `arxiv-qa/README.md:19-26`). Its
   dispatcher keys off object *names* and reads a `<id>/<id>.meta.json` that must carry an
   `arXiv_submissions` block. In legacy 1.5, `arxiv-bin/sync_submission.sh` rsynced submission
   files into `gs://arxiv-submission/<id>` at submit time and after processing — that rsync is
   what fired the QA notifications. submit-ce must reproduce that: at finalize, land the
   submission's `pdf`, `source tar.gz`, and an `arXiv_submissions`-shaped `meta.json` **directly
   into the `arxiv-submission` bucket**.

2. **Domain-event topic (for future/other consumers).** Keep and harden the branch's
   `EventList` publishing so other services can subscribe to submission domain events. QA will
   not consume this today, but it is the longer-term event stream.

Trade-off already accepted: writing directly to the prod `arxiv-submission` bucket (rather than
a separate sync step) means submit-ce takes a dependency on that bucket and on the
notification config that already exists.

## Current-state facts (verified)

**What QA consumes (the parity target):**
- `arxiv-qa/README.md:19-26` — `arxiv-submission` bucket has Pub/Sub notifications enabled
  (topic `projects/arxiv-production/topics/arxiv-submission`); files synced into
  `gs://arxiv-submission/<submission_id>`.
- `arxiv-qa/cloud_functions/dispatcher/main.py:60-72` — dispatcher matches object names with
  **start-anchored** regexes: `(\d+)\/\1\.pdf` (line 61, `re.match`), `(\d+)\/\1(\.tar\.gz|\.gz)`
  (line 60), `(\d+)\/\1(\.meta.json)` (line 67), `(\d+)\/\1(\.pdfinfo.json)` (line 64). Because
  `pdf`/`pdfinfo`/`meta` use `re.match`, the object name must **start** with the digits — i.e.
  **no bucket prefix** is allowed.
- `arxiv-qa/cloud_functions/dispatcher/main.py:170-172` — reads `<id>/<id>.meta.json` and pulls
  `metadata['arXiv_submissions']['submission_id' | 'type' | 'source_format']`.
- `arxiv-qa/cloud_functions/check_authors/main.py:229,280,326,354` — downstream QA also reads
  `md["arXiv_submissions"]["type"]` and `md["arXiv_submissions"]["authors"]`.

**What submit-ce produces today:**
- `submit_ce/implementations/file_store/gs_file_store.py:503-504` — preview path is
  `{gs_prefix}/{submission_id}/{submission_id}.pdf` ✅ matches QA layout when `gs_prefix==""`.
- `gs_file_store.py:500-501` — source package is `{gs_prefix}/{submission_id}/{submission_id}.tar.gz`
  ✅ matches.
- **No `meta.json` is ever written.** `store_zzrm`/`store_directives`/etc. exist
  (`gs_file_store.py:562-567`, `509-513`) but nothing emits an `arXiv_submissions` block. ← gap.
- `submit_ce/ui/config.py:89-96` — `STORE` (`gs`/`null`), `STORE_GS_BUCKET` (default
  `arxiv-submit-dev`), `STORE_GS_PREFIX` (default `""`). No QA-bucket or topic settings; the
  prod working bucket is **not** `arxiv-submission`.
- `submit_ce/ui/backend.py:25-44` — `config_backend_api()` builds `GsFileStore` and returns a
  bare `FlaskSubmitImplementation`. **`PubsubEventSubmitImplementation` is never instantiated**
  and there is no config flag to enable it.

**The submit event:**
- `submit_ce/domain/event/__init__.py:969-1019` — `FinalizeSubmission` is the submit event.
  `project()` sets `status = SUBMITTED` and `submitted = now` (lines 994-995).
  `CONSEQUENCE_TYPES = frozenset({AddHold, EmailSubmitterFinalizeMsg})` (line 982);
  `consequences()` (998-1019) emits those follow-on events.
- `submit_ce/domain/event/base.py:243-285` — `EventWithSideEffect` has `validate_under_lock()`
  and `execute(api, submission)` run inside the locked transaction; its docstring (line 246)
  states these **cannot be serialized to JSON**.

**Domain-event publisher (current, buggy):**
- `submit_ce/implementations/pubsub/__init__.py:33-37` — `save(*event, submission_id=...)` calls
  `inner_api.save(...)` then `self.publisher.publish(self.topic, self.serialize_msg(event))`.
- `pubsub/__init__.py:75-81` — `serialize_msg(*events)` does `EventList([item[0] for item in events])`.
  Because `save` passes the whole `event` *tuple* as a single positional arg, `events == (event,)`,
  so `[item[0] for item in events]` yields **only the first event** — multi-event saves drop the
  rest. (The passing test `tests/test_pubsub_impl.py:39` only ever sends one event, masking this.)
- The publisher only sees the **input** events, never the **consequences** that `inner_api.save`
  generated and committed (e.g. `AddHold`, `EmailSubmitterFinalizeMsg`), so subscribers never see
  them.
- `topic` is passed to the constructor but nothing constructs the impl, so there is no config path.

**Legacy `arXiv_submissions` mapping (the source of meta.json values):**
- `submit_ce/implementations/legacy_implementation/models.py:46` — `__tablename__ = 'arXiv_submissions'`.
- `models.py:273-330` — `update_from_submission()` projects a `Submission` onto the row, incl.
  `title` (293), `abstract` (294), `authors` (295), `source_format` (325-328, `submission.source_format.value`),
  `version` (303). The legacy `type` column (`new`/`rep`/`cross`/`jref`/`wdr`) comes from
  `submission_type` (see `db.py:704` round-trip `SubmissionType(row.type)`).
- `submit_ce/domain/uploads.py:14-25` — `SourceFormat` enum: `TEX="tex"`, `PDFTEX="pdftex"`,
  `PDF="pdf"`, `PS="ps"`, `HTML="html"`, etc. — values already match what QA's dispatcher tests
  against (`src_format == 'pdf'`/`'tex'`/`'pdftex'`).

## Requirements

1. On `FinalizeSubmission` (the submit event), the following three objects exist in
   `gs://arxiv-submission/` with **no prefix**:
   - `<submission_id>/<submission_id>.pdf`
   - `<submission_id>/<submission_id>.tar.gz`
   - `<submission_id>/<submission_id>.meta.json`
2. `meta.json` contains a top-level `"arXiv_submissions"` object including at least
   `submission_id` (int), `type` (legacy code, e.g. `"new"`), `source_format` (e.g. `"tex"`/`"pdf"`),
   `authors`, `title`, `abstract` — the keys QA's dispatcher and `check_authors` read.
3. The domain-event topic publisher is wired into the app, configurable, and corrected so it
   publishes the events that were actually committed (including consequences), without crashing
   on side-effect events.
4. Both mechanisms are **off by default** and enabled by explicit config; no behavior change
   when unconfigured (CI and local dev unaffected).

## Design overview

Two independent tracks, gated by separate config flags.

### Track A — QA file landing (the 1.5-parity work)

The pdf and source tarball already land in the working store with the right *names*, but the
working store's bucket (`arxiv-submit-dev`) and optional `STORE_GS_PREFIX` are wrong for QA
(QA's regexes are start-anchored, so any prefix breaks matching). So Track A uses a **dedicated
QA publisher** that writes into `arxiv-submission` with an empty prefix, independent of the
working store.

Hook point: a new **`EventWithSideEffect` consequence of `FinalizeSubmission`** (call it
`PublishToQa`). This keeps the action inside the event-sourced model (traceable, declared in
`CONSEQUENCE_TYPES`, runs under the row lock via `execute()`), matching how `AddHold` and the
finalize email already work. `execute()` will:
1. Copy `<id>.pdf` and `<id>.tar.gz` from the working store into `gs://arxiv-submission/<id>/`
   (server-side GCS copy; no download/upload round-trip).
2. Build the `arXiv_submissions` dict from the submission's legacy row and write
   `<id>/<id>.meta.json`.

`PublishToQa` is an `EventWithSideEffect`, so it is **not** JSON-serializable and must never be
sent on the domain-event topic — which is fine, it is a side effect, not a fact for subscribers.

meta.json content is generated by **reusing the legacy projection**: instantiate/lookup the
`models.Submission` row (already produced by `update_from_submission`, `models.py:273-330`) and
serialize the QA-relevant columns under `{"arXiv_submissions": {...}}`. This guarantees the
values match what classic produced (true 1.5 parity) rather than re-deriving them.

*Alternative considered and rejected:* point the working `GsFileStore` directly at
`arxiv-submission`. Rejected because (a) QA's start-anchored regexes forbid the `STORE_GS_PREFIX`
that dev/test rely on, and (b) it would dump *all* intermediate working files (`gcp_compile.log`,
`directives.json`, `src/…`) into the prod QA bucket on every edit, not just the finalized
artifacts. A dedicated finalize-time publisher writes exactly the three objects QA needs.

*Alternative considered and rejected:* a separate post-finalize sync step (cron/script like
legacy). Rejected per the product decision to write directly to `arxiv-submission`; an in-process
side effect is simpler to reason about and reuses the existing GCS client.

### Track B — Domain-event topic (harden + wire)

- Construct `PubsubEventSubmitImplementation` in `config_backend_api()` and wrap the
  `FlaskSubmitImplementation` when `PUBSUB_ENABLED`.
- Fix `save()`/`serialize_msg()`:
  - Publish the **committed** event list returned by `inner_api.save()` (`answer[1]`), not the
    raw input args — this captures consequences and the corrected `created`/`committed` fields.
  - Filter out `EventWithSideEffect` instances before serializing (they are not JSON-serializable
    per `base.py:246`); document that side-effect events are intentionally not broadcast.
  - Remove the double-tuple bug (`serialize_msg` should take a clean `list[Event]`).
  - Decide failure semantics: the DB commit has already happened when we publish, so a publish
    failure must **not** raise back into the request (which already succeeded). Log an error and
    continue. (Acknowledge the resulting at-least-once / possibly-missed-message gap; a true
    transactional outbox is out of scope.)
- Pull `topic` (and GCP project) from config.

## Critical files

- **`submit_ce/ui/config.py:89-96`** — add settings (all `SUBMIT_API_`-prefixed, safe defaults
  that leave both tracks off):
  - `QA_PUBLISH_ENABLED: bool = False`, `QA_BUCKET: str = "arxiv-submission"`.
  - `PUBSUB_ENABLED: bool = False`, `PUBSUB_TOPIC: str = ""` (full `projects/.../topics/...`).
- **`submit_ce/ui/backend.py:25-44`** — in `config_backend_api()`: pass the QA publisher into the
  store/impl when `QA_PUBLISH_ENABLED`; wrap the returned `FlaskSubmitImplementation` in
  `PubsubEventSubmitImplementation(publisher, settings.PUBSUB_TOPIC, inner)` when `PUBSUB_ENABLED`.
- **`submit_ce/implementations/file_store/gs_file_store.py`** — add `_meta_json_path()` (next to
  `_preview_path`, line 503) and a `store_meta_json(submission_id, content: dict)` (model on
  `store_zzrm`, 562-567). Add a QA-target writer: either a second `GsFileStore` bound to
  `QA_BUCKET` with empty prefix, or a small `copy_blob_to(bucket, name)` helper using
  `bucket.copy_blob` for server-side copy of the pdf/tar.gz.
- **`submit_ce/api/file_store.py`** — add abstract `store_meta_json(...)` if the publish path goes
  through the `SubmissionFileStore` interface (keeps `NullFileStore` working in tests).
- **`submit_ce/domain/event/__init__.py:982,998-1019`** — add `PublishToQa` to
  `FinalizeSubmission.CONSEQUENCE_TYPES` and emit it from `consequences()` (only when
  `submission.submission_id` is set and the finalize otherwise succeeds).
- **New event class `PublishToQa(EventWithSideEffect)`** (in `domain/event/process.py`, alongside
  the other side-effect/process events) — `execute(api, submission)` copies pdf+source into
  `QA_BUCKET` and writes `meta.json`; `project()` is a no-op (or records a flag). Add it to the
  consequence graph test fixtures (`domain/event/tests/test_consequences_graph.py`).
- **`submit_ce/implementations/legacy_implementation/models.py:273-330`** — add a
  `to_meta_json()` / `arxiv_submissions_dict()` helper on the row (reusing the same field
  projection) so meta.json values stay in lockstep with the DB row.
- **`submit_ce/implementations/pubsub/__init__.py:33-37,75-81`** — fix `save()` to publish
  `answer[1]` filtered of `EventWithSideEffect`; rewrite `serialize_msg` to accept a clean
  `list[Event]`; wrap publish in try/except with error logging.

## What this deliberately does NOT do

- Does not modify the QA pipeline (`arxiv-qa`) — parity means matching what it already consumes.
- Does not enable either track by default; prod enablement is an ops/config step (the
  `arxiv-submission` notification config already exists).
- Does not build a transactional outbox or delivery guarantees for the domain-event topic; a
  best-effort post-commit publish with error logging is the accepted scope.
- Does not implement replacement/withdrawal/cross-list `type` handling beyond mapping
  `submission_type` to the legacy code; new submissions (`type == "new"`) are the primary path.
  (Note as a follow-up if QA needs `rep`/`cross`/`wdr` artifacts.)
- Does not change the working-store bucket layout or `STORE_GS_PREFIX` behavior for dev/test.
- Does not add a new subscriber service.

## Verification

1. **meta.json shape (unit):** build a finalized test submission; assert
   `json.loads(meta)["arXiv_submissions"]` contains `submission_id` (int), `type`,
   `source_format`, `authors`, `title`, `abstract`, and that `source_format` is one of the
   `SourceFormat` values QA checks (`tex`/`pdf`/`pdftex`).
2. **Object names (unit):** assert the three written object names match QA's exact regexes —
   `re.match(r"(\d+)/\1\.pdf$", name)`, `re.search(r"(\d+)/\1(\.tar\.gz|\.gz)", name)`,
   `re.match(r"(\d+)/\1\.meta\.json", name)` — with **no prefix**.
3. **Finalize lands files (integration):** with `QA_PUBLISH_ENABLED` and a fake/emulated
   `arxiv-submission` bucket, run a `FinalizeSubmission` through `SubmitApi.save()` and assert the
   three blobs exist in the QA bucket. Confirm `PublishToQa` appears as a declared consequence and
   the consequence-graph cycle test still passes.
4. **Domain-event publish (integration):** with the pubsub emulator (existing
   `pubsub/tests/conftest.py`), finalize a submission and assert the published `EventList`
   round-trips via `TypeAdapter(EventList).validate_json(...)`, contains **all** committed
   non-side-effect events (regression for the first-event-only bug), and that a publish failure
   does not raise out of `save()`.
5. **No-op when disabled:** with both flags false, `config_backend_api()` returns a bare
   `FlaskSubmitImplementation`, nothing is written to any QA bucket, and the existing test suite
   (`uv run pytest --ignore=submit_ce/implementations/pubsub`) passes unchanged.
6. **Lint:** `uv run ruff check submit_ce`.

## Suggested order of implementation

1. **meta.json generation** — `arxiv_submissions_dict()` on the legacy row +
   `store_meta_json()` on the file store + abstract method. → verify (1).
2. **QA publisher** — `PublishToQa` side-effect event + copy pdf/tar.gz into `QA_BUCKET` +
   add to `FinalizeSubmission.CONSEQUENCE_TYPES`/`consequences()`. → verify (2),(3).
3. **Config + backend wiring for Track A** — `QA_PUBLISH_ENABLED`/`QA_BUCKET`; wire in
   `config_backend_api()`. → verify (3),(5).
4. **Harden the domain-event publisher** — fix `save()`/`serialize_msg`, publish committed +
   filtered events, error-log on publish failure. → verify (4).
5. **Config + backend wiring for Track B** — `PUBSUB_ENABLED`/`PUBSUB_TOPIC`; wrap impl. →
   verify (4),(5).
6. **Full pass** — run both test invocations and ruff. → verify (5),(6).

## Comparison with QA-100 (`arxiv-qa/snapshot_submission/`, PR #70)

QA-100 created `arxiv-qa/snapshot_submission/` — a **standalone CLI** (`main.py -s <id>`) invoked by
the **legacy Perl submit system** at submit time (replacing the older `snapshot_md.py`). It reads
files from the legacy `/data/new/<shard>/<id>/` filesystem, uploads them to a GCS bucket, snapshots
the DB, writes the meta.json to the QA bucket, and optionally publishes to Pub/Sub. Config comes
from `config.ini` + Secret Manager. It is the **reference producer of the schema-1.2 metadata** that
this submit-ce work mirrors, integrated into the app and triggered at `FinalizeSubmission`.

### Output format — verified identical (schema 1.2)

Checked field-for-field against QA-100's `example.meta.json`:

| Element | QA-100 | submit-ce | Match |
|---|---|---|---|
| `name` / `version` | "arXiv Submission Snapshot Metadata" / `1.2` | same | ✅ |
| 5 source tables (`arXiv_submissions`, `_category`, `_near_duplicates`, `_abs_classifier_data`, `_classifier_data`) | `object_to_dict`, classifier `json` parsed | same (`domain/qa_metadata.build_snapshot`) | ✅ |
| `metadata_checksum` | `str(checksum_metadata(row))` | same helper + call | ✅ |
| `urls` with `#<generation>` | from uploaded blob | from store blob (`GsFileStore.get_qa_artifact_info`) | ✅ |
| `crc32c` per file | from blob | same blob fetch | ✅ |
| artifact keys | pdf, source, directives.json, gcp-compile.json, gcp_compile.log, gcp_preflight.json, source.log | same | ✅ |

### Architectural differences — by design

| Aspect | QA-100 (CLI) | submit-ce |
|---|---|---|
| Trigger | legacy Perl at submit time | `FinalizeSubmission` (finalize controller) |
| DB access | new read-only conn via Secret Manager | app's existing session |
| Config | `config.ini` + ServiceAccountJSON | `Settings` env vars + ADC |
| Layering | one flat script | domain `build_snapshot` + `controllers/qa_metadata` + file-store method |
| `--anonymize` | yes | not ported (not needed for in-app publish) |

These are appropriate: submit-ce replaces the legacy submit, so finalize is the equivalent hook.

### What was actually built (vs. the Track A/B plan above)

The implementation diverged from the original two-track plan; it follows QA-100's shape instead:
- meta.json is assembled by `submit_ce/domain/qa_metadata.py` (`build_snapshot`, schema 1.2) and
  `submit_ce/ui/controllers/qa_metadata.py` (`build_qa_metadata`, DB queries + ORM→dict).
- `GsFileStore.store_qa_metadata()` writes `<id>/<id>.meta.json` to the QA bucket
  (`QA_GS_BUCKET`/`QA_GS_PREFIX`), gated by `QA_GS_UPLOAD_ENABLED`.
- `GsFileStore.get_qa_artifact_info()` supplies `urls` (with generation) + `crc32c` from the
  already-stored blobs — submit-ce does **not** re-upload the files.
- `final.py` `_upload_qa_metadata()` (bucket) and `_pubsub_qa_metadata()` (topic, gated by
  `QA_PUBSUB_ENABLED`/`QA_PUBSUB_TOPIC`) run after a successful finalize, best-effort.
- The `PublishToQa` `EventWithSideEffect` consequence and the Track B domain-event topic harden
  (`PubsubEventSubmitImplementation` fixes) were **not** implemented; the user confirmed the submit
  message should carry the meta.json snapshot, not the typed `EventList`.

### Open discrepancies to resolve (config/wiring, not message shape)

1. **Pub/Sub topic name mismatch.** QA-100 publishes to **`submit-info`** (`config.ini`:
   `PubsubTopic=submit-info`). submit-ce default `QA_PUBSUB_TOPIC` is
   `projects/arxiv-development/topics/submission-qa-metadata`. If QA's consumer subscribes to
   `submit-info`, submit-ce messages won't be seen — align the topic.
2. **File `urls` reference a different bucket/layout — acceptable.** QA-100 uploads pdf/source/etc.
   into `SnapshotBucket = arxiv-dev-submission` at the **bucket root** (`gs://arxiv-dev-submission/6106564.pdf`)
   and points `urls` there. submit-ce does not re-upload; its `urls` point at the submit store
   (`STORE_GS_BUCKET`, default `arxiv-submit-dev`) under `<prefix>/<id>/<id>.pdf`. This bucket/prefix
   difference is fine — it is just for development testing, and a QA consumer dereferences the
   `urls` directly rather than assuming a fixed bucket/layout.
