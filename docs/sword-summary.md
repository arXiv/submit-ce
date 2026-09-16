# How a SWORD deposit becomes a submission

SUBMISSION-29. How the SWORD deposit API turns a depositor's uploaded files into a
submission that the Flask submit UI lists, and where that pipeline currently stops.

Companion documents, under [`docs/prs/submission-29-sword-api/`](prs/submission-29-sword-api/):
[implementation plan](prs/submission-29-sword-api/20260730-plan.md),
[code review](prs/submission-29-sword-api/20260804-code-review.md),
[security review](prs/submission-29-sword-api/20260804-security-review.md),
[design review](prs/submission-29-sword-api/20260810-design-review.md).
Also the [manual testing guide](sword-getting-started.md).

## The short version

SWORD is a **two-step** protocol. Files and metadata arrive in separate requests,
and it is the *second* one that creates anything in the database.

```mermaid
flowchart LR
    A["POST zip<br/>Content-Type: application/zip"] -->|201 Created| B["Staging bucket<br/>gs://…/sword-deposits/"]
    C["POST Atom entry<br/>with rel=related links"] -->|202 Accepted| D["Domain events"]
    B -.->|"bytes read back"| D
    D --> E["arXiv_submissions row<br/>+ files in workspace"]
    D --> F["arXiv_tracking row"]
    E --> G["Visible in the submit UI"]
    F --> H["GET /resolve/app/id"]

    style B fill:#e8f0fe,stroke:#4285f4
    style E fill:#e6f4ea,stroke:#34a853
    style G fill:#e6f4ea,stroke:#34a853
```

A media deposit stages bytes and returns an id. Nothing is in the database yet. The
wrapper deposit names those ids, and *that* is when a submission is created — in a
single transaction, as the same domain events an interactive submission produces.

## Step 1 — media deposit

`POST /sword-app/{collection}-collection` with a file body.

```mermaid
sequenceDiagram
    autonumber
    participant C as Depositor client
    participant R as POST route
    participant A as sword.auth
    participant S as DepositStore (GCS)

    C->>R: POST /sword-app/cs-collection<br/>Content-Type: application/zip<br/>Authorization: Basic, Content-MD5
    R->>A: depositor_from_credentials()
    A->>A: 1. authenticate (nickname + password)
    A->>A: 2. authorize (flag_xml AND flag_proxy,<br/>veto_status ok, not banned)
    A->>A: 3. registered_license (arXiv_sword_licenses)
    A-->>R: Depositor
    R->>R: is_valid_collection / user_may_post_to
    R->>R: check_deposit_size (50 MiB)
    R->>R: verify_md5
    R->>S: allocate_id() → 26080001
    S->>S: CAS on the counter object
    R->>S: save(id, owner, content_type, bytes)
    R->>S: save_entry(id, atom_entry, owner)
    R-->>C: 201 Created + <link rel="edit-media">
```

The bytes land in a **staging** area keyed by deposit id, not in any submission:

```
<prefix>/nextid                    the allocation counter
<prefix>/<yymm>/<id>.<ext>         the deposited bytes
<prefix>/<yymm>/<id>.atom          the response entry
```

A depositor repeats this per file. The manual recommends bundling TeX sources as
one zip, and depositing large figures separately
([`arxiv-docs/source/help/submit_sword.md:317`](https://github.com/arXiv/arxiv-docs/tree/develop/source/help/submit_sword.md#L317)).

## Step 2 — wrapper deposit, which creates the submission

Same URL, `Content-Type: application/atom+xml;type=entry`. The body carries the
metadata plus `rel="related"` links naming the deposits from step 1.

```mermaid
sequenceDiagram
    autonumber
    participant C as Depositor client
    participant R as POST route
    participant P as atom.parse
    participant I as ingest
    participant API as SubmitApi.save
    participant DB as classic DB
    participant FS as SubmissionFileStore

    C->>R: POST wrapper (Atom entry)
    R->>P: parse_wrapper()
    P->>P: title, summary, authors, contact, categories
    P->>P: resolve rel="related" → deposit ids
    P->>P: owner check per deposit (ENOWN)
    P-->>R: WrapperMetadata
    R->>I: ingest_wrapper()
    I->>I: metadata_events()
    I->>I: upload_events() — read staged bytes back
    I->>API: save(*events) — ONE transaction
    API->>DB: INSERT arXiv_submissions
    API->>DB: INSERT submit_ce_event × n
    API->>FS: unpack archive into the workspace
    API-->>I: Submission
    I->>DB: record_tracking() → arXiv_tracking
    I-->>R: submission_id
    R-->>C: 202 Accepted + tracking link
```

### The event sequence

[`submit_ce/sword/ingest.py`](https://github.com/arXiv/submit-ce/tree/develop/submit_ce/sword/ingest.py)'s `metadata_events` and `upload_events` build exactly the stream an
interactive submission produces — which is the point of doing this inside submit-ce
rather than beside it:

```mermaid
flowchart TD
    subgraph metadata["metadata_events()"]
        E1[CreateSubmission] --> E2["SetProxyInformation<br/>contact author + proxy"]
        E2 --> E3["ConfirmPolicy<br/>agreement_id=1"]
        E3 --> E4["SetLicense<br/>from arXiv_sword_licenses"]
        E4 --> E5[SetTitle]
        E5 --> E6[SetAbstract]
        E6 --> E7[SetAuthors]
        E7 --> E8[SetPrimaryClassification]
        E8 --> E9["AddSecondaryClassification × n"]
        E9 --> E10["optional: SetComments, SetJournalReference,<br/>SetDOI, SetReportNumber, SetACM/MSCClassification"]
    end
    subgraph files["upload_events()"]
        E11["UploadArchive — per zip, unpacked"]
        E12["UploadFiles — everything else"]
    end
    E10 --> E11 --> E12 --> SAVE["api.save(*events)"]

    style SAVE fill:#e6f4ea,stroke:#34a853
```

Everything goes through a **single** `SubmitApi.save`, so a validation failure
anywhere leaves no partial submission.

### Where the files actually move

This is the transition the question is really about. `upload_events` reads each
staged deposit back out of the SWORD bucket and re-wraps it in the shape the upload
events expect:

```python
staged = StagedFile(filename=f"{deposit_id}.{deposit.extension}",
                    content_type=deposit.content_type,
                    stream=io.BytesIO(data))
if deposit.extension == "zip":
    events.append(UploadArchive(creator=creator, client=client, file=staged))
else:
    loose.append(staged)
```

Applying the event copies the bytes into the *submission's* workspace in
`SubmissionFileStore`. A zip goes through `UploadArchive` so it is unpacked;
anything else is added as a loose file. The staging copy is left where it is and
ages out under a bucket lifecycle rule ([`arxiv-docs/source/help/submit_sword.md:744`](https://github.com/arXiv/arxiv-docs/tree/develop/source/help/submit_sword.md#L744)).

## What makes it appear in the submit UI

Two fields, both set during step 2.

```mermaid
flowchart LR
    D["Depositor account<br/>e.g. vtex"] -->|"depositor_user()"| SID["arXiv_submissions<br/>.submitter_id"]
    CA["Contact author<br/>from the wrapper"] -->|SetProxyInformation| SN["submitter_name<br/>submitter_email"]
    SID --> Q["load_submissions_for_user()"]
    ST["status = 0 (working)"] --> Q
    Q --> UI["'My submissions' in the UI"]

    style UI fill:#e6f4ea,stroke:#34a853
```

The UI's list query is:

```python
select(models.Submission).where(
    models.Submission.submitter_id == int(user_id),
    models.Submission.status.in_([0, 1, 2, 4]))
```

Two consequences worth being explicit about:

- **The submission belongs to the depositing account, not the author.** A proxy
  depositor like `vtex` sees it in *their* list. The author reaches it through
  `SetProxyInformation`, which fills `submitter_name` / `submitter_email`.
- **A fresh deposit is status 0 (working)**, which is in that list, so it appears
  immediately and is editable through the normal workflow.

## Step 3 — the worker finishes it

[`submit_ce/sword/ingest.py`](https://github.com/arXiv/submit-ce/tree/develop/submit_ce/sword/ingest.py) deliberately stops short:

> Compilation and `FinalizeSubmission` are **not** done here. `FinalizeSubmission`
> requires `source_format`, which only preflight can determine, so finalizing is
> left to the async compile path.

That path is [`submit_ce/sword/worker.py`](https://github.com/arXiv/submit-ce/tree/develop/submit_ce/sword/worker.py), driven by
[`submit_ce/sword/worker_loop.py`](https://github.com/arXiv/submit-ce/tree/develop/submit_ce/sword/worker_loop.py). It cannot ride on the deposit
request: preflight and compile are blocking calls with an 840-second timeout
each, and both run inside `SubmitApi.save`, which holds `SELECT … FOR UPDATE` on
the submission row throughout. Close to half an hour with the row locked, against
a 202 that promises asynchronous ingestion.

```mermaid
stateDiagram-v2
    [*] --> staged: POST media (201)
    staged --> created: POST wrapper (202)
    created --> analysed: StartPreflight<br/>SetSourceFormat
    analysed --> prepared: StartDirectives<br/>StoreZzrm
    prepared --> compiled: StartCompileSource<br/>or InstallPdfPreview
    compiled --> finalized: ConfirmSourceProcessed<br/>FinalizeSubmission
    finalized --> announced: announcement pipeline
    announced --> [*]

    note right of created
        status 0, visible in the UI
        tracking says "incomplete"
    end note
    note right of prepared
        00README.json is what
        /convert requires -- without
        it: "ZZRM missing or
        underspecified"
    end note
    note right of finalized
        status 1, tracking says
        "submitted"; emails the
        submitter and moderators
    end note
```

Every step is guarded on state that survives a restart — a file in the store, or a
field on the submission — so a worker killed mid-compile resumes rather than
redoing work. Three of the steps call tex2pdf: `/preflight`, `/directives` and
`/convert`.

**It refuses to finalize a submission with no preview.** Nothing in the domain
stops `FinalizeSubmission` queueing a paper whose compile produced no PDF;
interactively the Submit button is gated on the preview, and a worker has no such
gate. A permanent failure is recorded in `arXiv_tracking.submission_errors` — the
column legacy used for the same purpose — which both takes the submission out of
the queue and shows the depositor why through `/resolve`.

Retryable failures are treated differently: a 5xx from tex2pdf, or a 401/403 from
expired credentials, says nothing about the deposit, so it is left alone and picked
up next pass.

Run it with [`local_sword_worker.py`](https://github.com/arXiv/submit-ce/tree/develop/local_sword_worker.py); it deploys as a Cloud Run
**Job** ([`cicd/cloudbuild-sword-worker-dev-arxiv.yaml`](https://github.com/arXiv/submit-ce/tree/develop/cicd/cloudbuild-sword-worker-dev-arxiv.yaml)), one pass per
execution. One worker at a time is the supported deployment: `SKIP LOCKED` stops a
second worker blocking on a compile, but it is not a lease.

## Tracking — what the depositor can poll

`GET /resolve/app/{sword_id}` is unauthenticated (matching legacy — `sword.conf`
gated `/sword-app` but not `/resolve`) and reads `arXiv_tracking`, whose `paper_id`
column is overloaded as a state field.

```mermaid
stateDiagram-v2
    [*] --> unknown: no tracking row
    [*] --> lookup: tracking row exists

    lookup --> failed: paper_id contains "failed"
    lookup --> unknown: submission missing
    lookup --> incomplete: not finalized
    lookup --> submitted: finalized
    lookup --> on_hold: is_on_hold
    lookup --> published: is_announced

    note right of failed
        "conflicting submission active"
        written by the legacy pipeline;
        undocumented in the manual
    end note
```

Precedence in `tracking._status_for` is announced → on hold → finalized →
incomplete. A held submission is still finalized in submit-ce's model, so the hold
has to win.

## The classic tables involved

```mermaid
erDiagram
    tapir_users ||--o| arXiv_demographics : "deposit privileges"
    tapir_users ||--o{ tapir_nicknames : "login name"
    tapir_users ||--o| arXiv_sword_licenses : "default license"
    tapir_users ||--o{ arXiv_submissions : "submitter_id"
    arXiv_submissions ||--o{ submit_ce_event : "event log"
    arXiv_submissions ||--o{ arXiv_submission_category : "categories"
    arXiv_submissions ||--o| arXiv_tracking : "sword_id"
    arXiv_documents ||--o{ arXiv_paper_owners : "who may replace"
    arXiv_documents ||--o{ arXiv_submissions : "announced paper"

    tapir_users {
        int user_id PK
        string email
        int flag_banned
    }
    arXiv_demographics {
        int user_id FK
        int flag_xml "required for SWORD"
        int flag_proxy "required for SWORD"
        string veto_status "must be ok"
        int flag_suspect "refused as contact"
    }
    arXiv_sword_licenses {
        int user_id FK
        string license "must be current, else ENLIC"
    }
    arXiv_submissions {
        int submission_id PK
        int submitter_id FK
        int status "0 working, 7 announced"
        int version
        string type "new or rep"
        string doc_paper_id
        int sword_id FK
    }
    arXiv_tracking {
        int sword_id PK
        string paper_id "submit/N, real id, or failed-*"
    }
    submit_ce_event {
        string event_id PK
        int submission_id FK
        string event_type
    }
```

Note `arXiv_submissions.sword_id` is a foreign key onto `arXiv_tracking.sword_id`,
so `record_tracking` has to insert the tracking row *before* back-linking it.

## The staging store

The deposit store is separate from the submission file store, with its own
interface and two implementations.

```mermaid
classDiagram
    class DepositStore {
        <<abstract>>
        +allocate_id(when) str
        +save(deposit_id, owner, content_type, data) StagedDeposit
        +get(deposit_id) StagedDeposit
        +read(deposit_id) bytes
        +save_entry(deposit_id, document, owner)
        +read_entry(deposit_id) bytes
        +extensions(deposit_id) List~str~
        +owner_of(deposit_id) str
        +owned_by(deposit_id, owner) bool
        +check_size(data)
        #_read_counter() Tuple
        #_write_counter(value, version) bool
    }
    class GsDepositStore {
        +gs_bucket
        +gs_prefix
        #_read_counter() "blob generation"
        #_write_counter() "if_generation_match"
    }
    class InMemoryDepositStore {
        +counter
        +version
        "STORE=null only"
    }
    class StagedDeposit {
        +deposit_id
        +owner
        +extension
        +content_type
        +size
        +created
    }
    DepositStore <|-- GsDepositStore
    DepositStore <|-- InMemoryDepositStore
    DepositStore ..> StagedDeposit : returns
```

`allocate_id` lives on the base class and is written in terms of the two counter
primitives, so both backends share the retry loop. On GCS the CAS is
`if_generation_match`, replacing the `flock` legacy used (`AtomPP.pm:586-596`);
generation `0` means "only if absent", which is how the counter is created.

`build_deposit_store` is exhaustive on `STORE` and raises on an unrecognized value —
falling through to memory would return 201 for deposits whose bytes live only in one
process's heap.

## Request dispatch

One route serves both deposit kinds; the content type decides.

```mermaid
flowchart TD
    P["POST /sword-app/{collection}-collection"] --> AUTH{credentials?}
    AUTH -->|no| E401["401 EAUTH"]
    AUTH -->|yes| GATES["authenticate → authorize → license"]
    GATES --> COL{valid collection<br/>and permitted?}
    COL -->|no| EVCOL["EVCOL / EAUTH"]
    COL -->|yes| SIZE{within 50 MiB?}
    SIZE -->|no| E413["413 ESIZE"]
    SIZE -->|yes| MD5{Content-MD5 matches?}
    MD5 -->|no| E412["412 EVMD5"]
    MD5 -->|yes| TYPE{content type}
    TYPE -->|"atom+xml;type=entry"| WRAP["_deposit_wrapper → ingest → 202"]
    TYPE -->|"zip, pdf, ps, …"| MEDIA["allocate_id + save → 201"]

    style E401 fill:#fce8e6,stroke:#ea4335
    style EVCOL fill:#fce8e6,stroke:#ea4335
    style E413 fill:#fce8e6,stroke:#ea4335
    style E412 fill:#fce8e6,stroke:#ea4335
    style WRAP fill:#e6f4ea,stroke:#34a853
    style MEDIA fill:#e6f4ea,stroke:#34a853
```

Check order follows `AtomPP.pm:218-343`: credentials, collection, permission, SWORD
headers, checksum, then id allocation. Size is checked before the checksum so an
oversize body is not hashed first, and before the dispatch so a wrapper is capped
too — legacy's `$CGI::POST_MAX` applied to the whole request regardless of type.

## Replacement

A replacement is a new **version** of an announced paper, not a new submission.

```mermaid
sequenceDiagram
    autonumber
    participant C as Depositor
    participant R as PUT route
    participant RE as sword.replace
    participant API as SubmitApi

    C->>R: PUT /sword-app/edit/{paper_id or NNNNNNNN.atom}
    R->>RE: resolve_target() — tracking lookup or paper id
    R->>RE: require_owner() — arXiv_paper_owners
    R->>RE: pending_submission_id()
    alt a version is already open
        RE-->>C: 400 EPSUB "submission pending, not replaceable"
    else clear
        R->>RE: announced_submission_id()
        R->>API: save(CreateSubmissionVersion, …)
        API-->>C: 202 Accepted
    end
```

### Three ids, three jobs

A replacement is where classic's one-row-per-version model and the domain's
one-submission model pull apart, and each of the three answers a different
question:

| | keyed by | why |
|---|---|---|
| **Identity** — workspace, event log, URL | the paper's *original* row | one submission, one history, whatever classic does underneath |
| **State** — version, status | the *newest* `new`/`rep` row | "what does this paper look like now" |
| **Discovery** — `sword_id` | the row *this deposit* created | legacy stamped the row it made (`Submission.pm:319-332`); it is how the worker finds work |

`_load` reconciles the first two: it projects the newest row while reporting the
id it was asked for, which is what `to_submission`'s `submission_id` override is
for. The worker reconciles the third, finding candidates by classic row and then
driving the paper by its origin — the files it needs to compile live under the
identity, not under the row that announced the version.

Getting any one of these wrong is quiet rather than loud. Filing events under the
version row split one paper's history in two; reading the requested row instead of
the newest reported a replaced paper as still at v1, so `CreateSubmissionVersion`
recomputed a version that already existed; and omitting the `sword_id` left the
replacement invisible to the worker, so it was never compiled.

## Design intent, in one line

A SWORD deposit produces *exactly* the event stream an interactive submission does.
That is what lets the same UI, workflow, and moderation tooling handle both without
knowing where a submission came from — and it is the reason this was built inside
submit-ce rather than as a separate service.
