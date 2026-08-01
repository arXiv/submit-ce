# SUBMISSION-29 — Reimplement arXiv's SWORD for submit 2.0

**Ticket:** [SUBMISSION-29](https://arxiv-org.atlassian.net/browse/SUBMISSION-29) · Assignee: Brian Maltzan · Reporter: Jake Weiskoff
**Branch:** `SUBMISSION-29-sword`
**Date:** 2026-07-30

## Context

arXiv's legacy SWORD deposit API is a Perl CGI (`arXiv::AtomPP::*`) fronted by Apache
basic auth. It lets conference organizers, proceedings editors and journal editors
programmatically deposit e-prints. The ticket asks for a backward-compatible
reimplementation for submit 2.0.

The goal is a **FastAPI service inside the `submit-ce` repo**, deployed as a second
Cloud Run service from the same image as the Flask UI, reusing submit-ce's
event-sourced domain layer so SWORD deposits produce submissions identical to
UI-created ones.

Trade-offs already accepted:

- **Same repo, separate process.** The domain/`api`/`implementations` layers are the
  reusable value; a separate repo would require pinning `submit-ce` as a git
  dependency (the repo already suffers this with `arxiv-base` pinned to a branch in
  `pyproject.toml`). But SWORD gets its own entrypoint and Cloud Run service, because
  its auth model (HTTP Basic), payload profile (large machine uploads) and
  blast-radius requirements differ from the interactive UI.
- **FastAPI**, chosen by the assignee. This forces two refactors that a Flask
  blueprint would not (see *Critical files*): `compile_api_service.py`'s reliance on
  `flask.current_app`, and the extraction of backend wiring out of `submit_ce/ui/`.
- **SWORD is legacy.** A more modern submission API may be added later.
  `submit_ce.api.app:app` and `submit_ce.fastapi.app:app` (referenced by `main.py`)
  are **reserved for that future API and must be left alone** — SWORD does not reuse
  either name and does not touch `main.py`.
- **Correctness over byte-compatibility.** Where the legacy implementation is
  demonstrably wrong, we emit the correct thing (decision 1 below).
- **The legacy public docs are the contract, but the Perl is authoritative.** The
  published manual disagrees with the code in several places, catalogued below.

### Decisions taken (2026-07-30)

| # | Question | Decision |
|---|---|---|
| 1 | Service-document category bug: byte-compat or correct? | **Correctness.** Emit each collection's own categories. |
| 2 | Is DCSIP dead? | **Dead.** `find . \| grep -i ResourceMap` on `lib-arxiv-039/nexus2:/data/new` returns nothing. Out of scope. |
| 3 | SWORD 1.0 or 1.3? | **1.3.** Matches `ServiceDoc.pm:57-58`. |
| 4 | Should `X-No-Op` be a true no-op? | **Yes.** Do not reproduce the legacy side effects. |
| 5 | Deposit size cap | **Raise 10 MB → 50 MB**, aligning with submit-ce's default. |
| 6 | Failure surface for deposits that never compile | **Same as legacy** — visible in `arXiv_tracking` with `submission_errors`. |

Additional scope added: **port the legacy Perl test suite** in
`arxiv-lib/t/arxiv_atompp/` and `arxiv-lib/t/lib/Test/Sword*` to pytest.

## Current-state facts (verified)

### Legacy SWORD implementation

| Fact | Anchor |
|---|---|
| CGI entrypoint; also mounted via Catalyst `WrapCGI` | `arxiv-httpd/cgi-bin/sword.pl:11-12`, `arxiv-submit/lib/arXiv/Controller/SwordCGI.pm:9-15` |
| Core server, 1620 lines | `arxiv-lib/lib/arXiv/AtomPP/AtomPP.pm` |
| Basic auth done **outside** the app by Apache `mod_authnz_external` → `cgi-bin/authenticate.pl`, realm `"SWORD at arXiv"`, HTTPS forced | `arxiv-httpd/conf/sword.conf:10-13,17,27-33` |
| `/sword-license` has **no** `<Location>` auth block → normal cookie auth, not basic | `arxiv-httpd/conf/sword.conf:20` |
| Method whitelist GET/POST/PUT/DELETE, else 405 with plain body `unsupported` (not XML) | `AtomPP.pm:147-153` |
| Authorization gate: requires `flag_xml` **AND** `flag_proxy`, `veto_status == 'ok'`, NOT `flag_banned` → else 401 + `EAUTH` | `AtomPP.pm:168-189` |
| License precondition: row in `arXiv_sword_licenses` whose license is in `current_licenses()` → else 412 + `ENLIC` | `AtomPP.pm:191-197`, `AtomPP.pm:1544-1558` |
| Collection == **group** (`grp_*`), not archive. Allowed groups from `arXiv_demographics.flag_group_*` | `AtomPP.pm:221-236`, `AtomPP.pm:555-573` |
| Deposit ids are `YYMM` + zero-padded counter from `/cache/atomdeposits/nextid` under `flock(LOCK_EX)`; grows past 8 digits when counter exceeds 9999 | `AtomPP.pm:582-604` |
| Media + wrapper deposits **both** consume ids from the same counter | `AtomPP.pm:256`, `AtomPP.pm:499` |
| Media workspace is a filesystem tree `/cache/atomdeposits/<yymm>/<id>.<ext>` plus an `<id>.atom` sidecar; ownership is the sidecar's `author/name` | `Config.pm:44`, `AtomPP.pm:656-682`, `AtomPP.pm:1122-1129` |
| Content-Type dispatch table | `AtomPP.pm:262-274` |
| MD5 accepted as base64-with-`==` **or** lowercase hex; mismatch → 412 `EVMD5` | `AtomPP.pm:1501-1510`, `AtomPP.pm:251-254` |
| SWORD headers: `Content-MD5`, `Content-Disposition` (parsed, ignored), `X-On-Behalf-Of`, `X-Verbose`, `X-No-Op`, `User-Agent`, `X-Packaging` | `AtomPP.pm:849-915` |
| `X-No-Op`: any value except literal `false` enables it | `AtomPP.pm:896-901` |
| Wrapper validation (categories, summary, links, contacts) | `AtomPP.pm:924-1231` |
| Ingestion forks; parent returns 202 immediately, child creates + processes submission and calls the abs classifier | `AtomPP.pm:1257-1268`, `AtomPP.pm:1279-1338`, `AtomPP.pm:1347-1367` |
| Depositor recorded as `proxy` on the submission | `AtomPP.pm:1193` |
| Response entry construction | `AtomPP.pm:1375-1484` |
| `POST_MAX` = 10 MiB; `maxUploadSize` = 10000 kB | `AtomPP.pm:9`, `ServiceDoc.pm:63` |
| Tracking XML `<deposit>` with `status`/`arxiv_id`/`submission_id`/`error` + **undocumented** base64 `autotex_log_b64` | `arxiv-submit/lib/arXiv/Controller/Sword.pm:23-103` |
| 39 error codes defined | `arxiv-lib/lib/arXiv/AtomPP/Config.pm:76-198` |
| Error entry shape | `arxiv-lib/lib/arXiv/AtomPP/Error.pm:44-121` |

### Category rules — and their arxiv-base replacements

The wrapper's category validation (`AtomPP.pm:1005-1085`) depends on four Perl
helpers. All four have direct equivalents in `arxiv-base`, so none needs reimplementing
from scratch.

| Perl helper | Anchor | arxiv-base replacement |
|---|---|---|
| `is_general_category` | `arxiv-lib/lib/arXiv/Categories.pm:1128-1135` | `CATEGORIES[cat].is_general` (`arxiv-base/arxiv/taxonomy/category.py:113`) |
| `get_archive_from_category` | `arxiv-lib/lib/arXiv/Categories.pm:938` | `CATEGORIES[cat].in_archive` (`category.py:112`) |
| `canonicalize_category` | `arxiv-lib/lib/arXiv/Categories.pm:988` | `CATEGORIES[cat].get_canonical()` (`category.py:121-127`) |
| `get_group_from_category` | `arxiv-lib/lib/arXiv/Categories.pm:1036` | `CATEGORIES[cat].get_archive().in_group` (`category.py:83,90,116-119`) |
| `is_valid_category_strict` | `arxiv-lib/lib/arXiv/Categories.pm:1164-1178` | `cat in CATEGORIES`, plus the bare-archive rule below |

The five general categories are **exactly** `physics.gen-ph`, `math.GM`, `cs.OH`,
`q-bio.OT`, `econ.GN` in both implementations — verified by enumerating
`is_general=True` in `arxiv-base/arxiv/taxonomy/definitions.py` against
`Categories.pm:1130-1134`. They agree, so no drift to reconcile.

`is_valid_category_strict` semantics worth preserving exactly: rejects anything
ending in `.`; a two-part `archive.subclass` must exist; a **bare archive name is
valid only if that archive does not require a subject class**. This is what makes
`cond-mat` invalid (tested in `03-cross.t:358-362`).

### Legacy behaviour the published docs get wrong

These matter because clients are built against observed behaviour, not the manual.

1. **Namespaces are `http://`, not `https://`.** `Config.pm:50-57` defines
   `ATOMNS`, `SWORDNS`, `ARXIVNS`, `ARXIVSCH` with `http://`. The manual renders them
   as `https://` throughout (e.g. `arxiv-docs/source/help/submit_sword.md:218-222`) —
   a docs-side bulk rewrite artifact. The live regression test confirms `http://`
   (`arxiv-test-regression/pytest/tests/test_sword.py:67-68`).
2. **10 error codes are undocumented.** The manual lists 29 (`submit_sword.md:810-841`).
   `Config.pm` additionally defines `ENCTS` 8193, `ERCTS` 8194, `EGCTS` 8195,
   `EGCCS` 8196, `ENOID` 2^29, `ENVID` 2^30, `EVXML` 2^31, `EPSUB` 2^32,
   `ERESM` 2^33, `ETITL` 2^34.
3. **`docx` is advertised but rejected.** It is in `@accepted_media_types`
   (`ServiceDoc.pm:78`) and the manual (`submit_sword.md:317`), but absent from the
   POST dispatch table (`AtomPP.pm:262-274`), so a `docx` deposit gets 415 `EMDTP`.
4. **Generator version is `1.1`**, not the `0.9` shown throughout the manual
   (`Config.pm:46`).
5. **Secondary-category lists are wrong in the service document.** Every non-test
   collection is given the categories of *all* groups, not its own
   (`ServiceDoc.pm:147-151`). Per decision 1, we fix this.
6. **Link scheme inconsistency in responses:** `edit`/`edit-media`/`content@src`/
   generator use `https://` (`AtomPP.pm:1425,1435,1477-1478`) but the `alternate`
   tracking link uses `http://` (`AtomPP.pm:1480`), as does Error.pm's generator uri.
7. **`ENTIT` ("No title") is never raised.** `$entry->title()` is used unchecked
   (`AtomPP.pm:1183`). `ENNAM` ("No author name") is likewise defined but unused.
8. **The manual's error examples show elements the code never emits.** Both worked
   examples include `<sword:userAgent>` and one includes `<sword:packaging>`
   (`submit_sword.md:412-413,869-871`), but `Error.pm:44-121` emits neither, and
   `show_error` builds a fresh Error object with nothing added
   (`AtomPP.pm:1518-1536`). The code is authoritative; those two elements are
   omitted here.
9. **`X-No-Op` still has side effects.** The forked child constructs
   `arXiv::Submit::Submission->new(...)` *before* checking noop and exiting
   (`AtomPP.pm:1280-1291`), so a no-op deposit can still create rows. Per decision 4,
   we do not reproduce this.

### The legacy Perl test suite (to be ported)

| File | Lines | What it covers |
|---|---|---|
| `arxiv-lib/t/arxiv_atompp/00-load.t` | 13 | Module import smoke test across all 7 `AtomPP::*` modules |
| `arxiv-lib/t/arxiv_atompp/01-basic.t` | 11 | Server constructs |
| `arxiv-lib/t/arxiv_atompp/auth.t` | 53 | The authorization gate against three fixture users |
| `arxiv-lib/t/arxiv_atompp/02-deposit.t` | 115 | Happy path: PDF media deposit → wrapper deposit |
| `arxiv-lib/t/arxiv_atompp/03-cross.t` | 421 | **Category rules — six negative cases with exact expected messages** |
| `arxiv-lib/t/arxiv_atompp/04-suspect.t` | 123 | Suspect-author rejection, via contributor email and via `X-On-Behalf-Of` |
| `arxiv-lib/t/lib/Test/Sword.pm` | 163 | HTTP client harness (builds the request, parses `edit_media_link`) |
| `arxiv-lib/t/lib/Test/Sword/Metadata.pm` | ~120 | Wrapper-XML builder |
| `arxiv-lib/t/arxiv_atompp/data/{sample.pdf,sample.xml}` | — | Fixtures |
| `arxiv-lib/t/db/sql/arXiv_sword_licenses.sql` | 3 | License rows for users 55596, 91310 |

The exact assertions worth porting verbatim:

- **`auth.t`** — user 55596 (`vtex`) and 91310 (`mscmt`) have `flag_xml`, `flag_proxy`,
  `veto_status == 'ok'`, not banned, and a `nonexclusive-distrib/1.0` sword license;
  user 109519 has neither flag and no license row (`auth.t:20-63`). These ids match
  the `arXiv_sword_licenses.sql` fixture.
- **`03-cross.t`** — six negative cases with exact response substrings:
  | Input | Expected substring | Code | Anchor |
  |---|---|---|---|
  | primary `test.dis-nn`, cross `physics.gen-ph` | `category element(s) invalid: cross to 'physics.gen-ph' not allowed` | `EVCTS` | `03-cross.t:98-102` |
  | 6 categories total | `new submissions may not exceed 4 secondary categories` | `ENCTS` | `03-cross.t:153-157` |
  | primary `test.dis-nn`, crosses `q-bio.OT` + `q-bio.PE` | `Crosses to general categories are not permitted in addition to other categories in the respective archives` | `EGCTS` | `03-cross.t:200-204` |
  | primary `physics.gen-ph` + crosses | `Crosses are not permitted when the primary category is also a general category` | `EGCCS` | `03-cross.t:253-257` |
  | primary `cs.OH`, crosses `cs.AI` + `cs.DL` | same as above | `EGCCS` | `03-cross.t:306-310` |
  | bare category `cond-mat` | `no such category: 'cond-mat'` | `EVCTS` | `03-cross.t:358-362`, `:409-413` |

  Note the category cap is **primary + 4 secondaries = 5 total**; the 6-entry list in
  the test trips `> 5` after the primary is de-duplicated and re-prepended
  (`AtomPP.pm:1018-1047`). Also note the emitted message for the gen-ph case carries a
  stray trailing quote — `qq{cross to '$cat' not allowed '}` (`AtomPP.pm:1058`).
- **`04-suspect.t`** — a contributor whose email belongs to a user with
  `arXiv_demographics.flag_suspect` yields `errorcode>512` (`EVCML`) and the message
  `must submit directly` (`04-suspect.t:96-100`). The same email in `X-On-Behalf-Of`
  fails at the **media deposit** step, not the wrapper step, because
  `process_sword_headers` runs on media POSTs too (`04-suspect.t:104-120`,
  `AtomPP.pm:885-890`).

#### Defects in the legacy test helpers — do not port these

`Test::Sword::Metadata` is buggy in ways that mean parts of the Perl implementation
were **never actually exercised**. The port must test these paths properly rather than
reproduce the helper's behaviour:

1. Malformed XML for the repeatable arXiv elements:
   `"  <arxiv:$entry xmlns:arxiv=\"$ARXIVNS\>\""` — the `\>\"` is broken.
2. `$entry =~ s/s$//` mutates the loop variable (which is the *attribute name*) inside
   the loop.
3. `<report_no>` is emitted **without** the `arxiv:` prefix, so it can never match
   `getElementsByTagNameNS(ARXIVNS, 'report_no')` (`AtomPP.pm:1163-1168`).
4. `my $ATOMNS` is declared twice; the xhtml div namespace is misspelled `xhmtl`.
5. `contributor` never emits `arxiv:affiliation` at all, even though `02-deposit.t`
   and `04-suspect.t` pass an `affiliation` into the contributor hash — it is
   silently dropped.

Consequence: extraction of `comment`, `journal_ref`, `doi`, `report_no`
(`AtomPP.pm:1163-1168`) and `affiliation` (`AtomPP.pm:940-942`) has effectively
**zero** legacy test coverage. Our port needs first-class tests for it.

`data/sample.xml` is also stale: it declares `xmlns:arXiv="http://arxiv.org/schemas/atom"`
— no trailing slash, capital X — which does not match `ARXIVNS`
(`http://arxiv.org/schemas/atom/`), and uses bare `term="test.dis-nn"` without the
scheme prefix. As written it would fail primary-category extraction with `ENPCT`.
Useful as a namespace-strictness negative fixture; useless as a happy-path one.

Finally, `02-deposit.t:44`, `03-cross.t:34-35` and `04-suspect.t:27` embed a live test
credential (`arXivTesterBot` / `testing!t`). **Do not carry these into the new suite** —
take them from environment/fixtures.

### submit-ce current state

| Fact | Anchor |
|---|---|
| `submit_ce/api/` is the **abstract interface layer**, not an HTTP API | `submit_ce/api/__init__.py:1-19` |
| No HTTP API exists yet; `main.py` points at `submit_ce.fastapi.app:app`, which does not exist — **reserved for a future modern API, leave alone** | `main.py:1-3` |
| Production image runs only the Flask UI | `Dockerfile:88-92` |
| DB-session seam already parameterized: `LegacySubmitImplementation(get_session=...)` | `submit_ce/implementations/legacy_implementation/flask_impl.py:8-31` |
| Backend wiring lives in `ui/` and imports Flask (`g`, `current_app`, `has_app_context`) | `submit_ce/ui/backend.py:7`, `submit_ce/ui/backend.py:98-108` |
| `compile_api_service.py` reads `current_app.api` in 5 places — the only Flask leak below `ui/` | `submit_ce/implementations/compile/compile_api_service.py:8,121,188,287,288` |
| `SubmitApi.save(*events, submission_id=None)` is the single write path | `submit_ce/api/submit.py:261-305` |
| Domain events available (incl. `SetProxyInformation`) | `submit_ce/domain/event/__init__.py:120-1353` |
| File events | `submit_ce/domain/event/file.py:130-242` |
| `SubmissionFileStore` is **submission-scoped** throughout | `submit_ce/api/file_store.py:35-475` |
| Size limit default is 50 MB — the target for the raised SWORD cap | `submit_ce/domain/size_limits.py:34`, `submit_ce/domain/size_limits.py:154` |
| No XML library in dependencies (no `lxml`) | `pyproject.toml` |

### Legacy tables — already modelled in `arxiv-base`

| Table | Model | Anchor |
|---|---|---|
| `arXiv_tracking` | `Tracking` (`tracking_id`, unique `sword_id`, `paper_id`, `submission_errors`, `timestamp`) | `arxiv-base/arxiv/db/models.py:1377-1388` |
| `arXiv_sword_licenses` | `SwordLicense` (`user_id`, `license`, `updated`) | `arxiv-base/arxiv/db/models.py:2079-2086` |
| `arXiv_submissions.sword_id` FK | `Submission.sword_id` | `arxiv-base/arxiv/db/models.py:1149` |
| `arXiv_demographics` flags | `Demographic.flag_xml`, `flag_proxy`, `flag_suspect`, `veto_status`, `flag_group_*` | `arxiv-base/arxiv/db/models.py:1998`, `:2010-2021` |
| `tapir_users.flag_banned` | `TapirUser` | `arxiv-base/arxiv/db/models.py:1915`, `:1938` |
| Paper ownership for replacement | `PaperOwner`, `Document`, `TapirNickname` | `arxiv-base/arxiv/db/models.py:873`, `:457`, `:1712` |

`arXiv_tracking.paper_id` is overloaded as a state field: `submit/<submission_id>`
while in flight, the real paper id once announced, or a string containing `failed`
(`AtomPP.pm:1312-1313`, `Controller/Sword.pm:29-31,50`).

Password checking is available in-process: `arxiv.auth.legacy.authenticate.authenticate()`
and `arxiv.auth.legacy.passwords.check_password()`. Current licenses:
`arxiv.license.CURRENT_LICENSES` (`arxiv-base/arxiv/license/__init__.py:124`).

### Existing regression tests

`arxiv-test-regression/pytest/tests/test_sword.py` (192 lines) and
`test_sword_gcp.py` (330 lines) drive the live endpoints: license toggle,
service document assertions, zip media deposit with `Content-MD5` → 201, metadata
wrapper POST → 202. These are the backward-compatibility gate.

## Requirements

1. `GET /sword-app/servicedocument` — per-user service document, `application/atomsvc+xml`,
   `Expires: +1d`, honouring `X-On-Behalf-Of`, advertising `<sword:version>1.3` and
   `<sword:maxUploadSize>50000`.
2. `POST /sword-app/<group>-collection` — media deposit for the accepted content
   types → 201 + `Location` + media link entry.
3. `POST /sword-app/<group>-collection` with `application/atom+xml;type=entry` —
   metadata wrapper → 202 + `Location` + wrapper entry, creating a real submission.
4. `GET /sword-app/getid/app/<id>` and `GET /sword-app/edit/<id>.atom` — retrieve a
   stored entry, owner-checked.
5. `PUT /sword-app/edit/<id>` — replacement, owner-checked → 202.
6. `DELETE` → 501; unsupported methods → 405.
7. HTTP Basic auth, realm `SWORD at arXiv`, plus the `flag_xml`/`flag_proxy`/
   `veto_status`/`flag_banned` authorization gate and the `arXiv_sword_licenses`
   precondition.
8. SWORD headers: `Content-MD5` (base64 and hex), `X-On-Behalf-Of`, `X-Verbose`,
   `X-No-Op` (true no-op), `X-Packaging`, `User-Agent`.
9. All 39 `arxiv:errorcode` values with matching HTTP statuses and `sword:error` bodies.
10. `GET /resolve/app/<sword_id>` — tracking XML, including `submission_errors` as the
    failure surface.
11. `arXiv_tracking` row written so tracking works immediately after 202.
12. `/sword-license` — depositor default-license page (Flask UI, not this service).
13. **50 MB deposit cap**, replacing the legacy 10 MB.
14. **The legacy Perl test suite ported to pytest**, per the table above.

## Design overview

### Service shape

A new FastAPI app at `submit_ce/sword/`, with its own entrypoint, deployed from the
existing image with a different Cloud Run `--command`.

Deliberately **not** `submit_ce/api/app.py` and **not** `submit_ce/fastapi/` — both are
reserved for the future modern submission API. `submit_ce/api/` is also already taken
by the abstract interface layer, so reusing it would compound existing confusion.
`main.py` is not touched.

```
submit_ce/sword/
  app.py            # FastAPI app factory
  auth.py           # HTTPBasic + authorization gate + license precondition
  collections.py    # group <-> collection mapping, allowed groups per user
  atom/
    parse.py        # wrapper entry -> validated dataclass
    render.py       # response entries, service document, sword:error
    ns.py           # namespace + scheme constants (http://, verified)
  errors.py         # the 39 codes: mnemonic -> (code, message, href, http_status)
  deposits.py       # media-deposit staging store (see below)
  ingest.py         # validated wrapper -> submit-ce domain events
  tracking.py       # /resolve/app/<id>
  tests/            # ported Perl suite + new unit tests
    conftest.py     # replaces Test::DB fixtures
    client.py       # replaces Test::Sword
    wrapper.py      # replaces Test::Sword::Metadata
    data/           # sample.pdf, namespace-strictness fixture
```

### The media-workspace problem, and the chosen answer

This is the one part of legacy SWORD that does not map onto submit-ce. Legacy media
deposits are **user-scoped and exist before any submission does**: a depositor POSTs
files one at a time, gets `edit-media` links, and only later POSTs a wrapper
referencing them. Deposits are retained ≥30 days (`submit_sword.md:735-744`) and are
referenceable across deposits, including replacements. submit-ce's
`SubmissionFileStore` is submission-scoped in every method
(`submit_ce/api/file_store.py:35-475`).

**Chosen: a separate deposit-staging store keyed by `sword_id`**, mirroring the legacy
filesystem layout onto GCS (`sword-deposits/<yymm>/<sword_id>.<ext>` plus the
`<sword_id>.atom` sidecar carrying the depositor username for ownership checks). The
submission is created only at wrapper POST, at which point staged bytes are copied
into the submission's workspace via the normal `SubmissionFileStore`/`UploadArchive`
path.

Rejected alternative: **eagerly create a submission on first media deposit.** It looks
simpler but breaks legacy semantics — one wrapper may reference media from several
independent deposits, replacements reference previously-deposited media, and every
un-wrapped media POST would leave an orphan submission. Not viable.

### Deposit-id allocation

Legacy allocates from a counter file under `flock` (`AtomPP.pm:582-604`), consumed by
both media and wrapper deposits. `arXiv_tracking.sword_id` cannot serve as the
allocator because media deposits consume ids that never reach that table.

**Chosen: a counter object in the deposit-staging bucket, updated with GCS
`if-generation-match`** — compare-and-swap with the same semantics as the legacy
`flock`, and no legacy-DB migration. Format preserved as `YYMM` + `%04d` counter,
because the GET route regex requires the first four digits to locate the entry
(`AtomPP.pm:367-368`) and clients parse ids out of `info:arxiv/app/<id>`.

### Async ingestion

Legacy forks: parent returns 202, child creates and processes the submission
(`AtomPP.pm:1257-1268`). The 202 contract only promises that *ingestion* is
asynchronous, not that the deposit call defers submission creation.

**Chosen:** synchronously create the submission, apply metadata events, copy staged
media in, and write the `arXiv_tracking` row — then return 202 and let compile/QA
proceed on submit-ce's existing async path, finalizing when compilation succeeds.
Tracking therefore works the instant the client receives 202, which the legacy
fork-based path does not reliably guarantee. Per decision 6, compile failures remain
visible via `arXiv_tracking.submission_errors`.

### Event mapping for a wrapper deposit

| SWORD element | submit-ce event |
|---|---|
| — | `CreateSubmission` |
| authenticated depositor | `SetProxyInformation` (legacy sets `proxy => username`, `AtomPP.pm:1193`) |
| contact from `X-On-Behalf-Of` / first contributor email | `ConfirmContactInformation` |
| `<title>` | `SetTitle` |
| `<summary>` | `SetAbstract` |
| `<contributor>` + `arxiv:affiliation` | `SetAuthors` |
| `arxiv:primary_category` | `SetPrimaryClassification` |
| `<category>` | `AddSecondaryClassification` (×n) |
| `arXiv_sword_licenses.license` | `SetLicense` |
| `arxiv:comment` / `journal_ref` / `doi` / `report_no` | `SetComments`, `SetJournalReference`, `SetDOI`, `SetReportNumber` |
| ACM / MSC scheme categories | `SetACMClassification`, `SetMSCClassification` |
| staged media from `rel="related"` links | `UploadArchive` / `UploadFiles` |
| after successful compile | `ConfirmSourceProcessed`, `ConfirmPreview`, `FinalizeSubmission` |

## Critical files

### New — service

| File | What to build |
|---|---|
| `submit_ce/sword/errors.py` | All 39 codes from `Config.pm:76-198`, each mapped to numeric code, message, `href`, and HTTP status. Statuses observed in the Perl: `EAUTH`→401, `ENLIC`→412, `EVMD5`→412, `EMDTP`→415, `EIMPL`→501, `ENAVL`/`EOVLD`→503, everything else→400 (`AtomPP.pm:1530`). |
| `submit_ce/sword/atom/ns.py` | `http://` namespaces and schemes, copied verbatim from `Config.pm:50-57`. Do not use the manual's `https://` forms. |
| `submit_ce/sword/atom/render.py` | Service document (`ServiceDoc.pm:96-171`) with per-collection categories (decision 1) and `maxUploadSize` 50000 (decision 5); media/wrapper response entries (`AtomPP.pm:1375-1484`); `sword:error` (`Error.pm:44-121`). Preserve the scheme mix in links (`https://` for edit/edit-media/content/generator, `http://` for `alternate`). |
| `submit_ce/sword/atom/parse.py` | Wrapper parsing + the full validation ladder from `AtomPP.pm:924-1231`. `summary` uses strict `> 20` (`AtomPP.pm:1088`); the `rel="related"` href regex is `^https?://\S+/sword-app/edit/((\d{4})\d{4,})` (`AtomPP.pm:1102`). Category rules via `arxiv.taxonomy` per the mapping table above. |
| `submit_ce/sword/auth.py` | `HTTPBasic` → `arxiv.auth.legacy.authenticate`; then the gate from `AtomPP.pm:183` against `Demographic`/`TapirUser`; then license check against `arxiv.license.CURRENT_LICENSES` (`AtomPP.pm:1553`). Username is the **tapir nickname** and case-sensitive (`submit_sword.md:726-727`). Also the `flag_suspect` check (`AtomPP.pm:1589-1607`). |
| `submit_ce/sword/collections.py` | `<abbrev>-collection` ↔ `grp_<abbrev>`, and allowed groups from `Demographic.flag_group_*` (`AtomPP.pm:555-573`). Note this is group membership, **not** `SubmitApi.categories_for_user`, which is endorsement-based (`submit_ce/api/submit.py:322-331`). |
| `submit_ce/sword/deposits.py` | Staging store + `YYMM####` id allocator via GCS `if-generation-match`. 50 MB body cap. |
| `submit_ce/sword/ingest.py` | Validated wrapper → the event sequence above, through `SubmitApi.save()`. Writes the `arXiv_tracking` row with `paper_id = submit/<submission_id>`. |
| `submit_ce/sword/tracking.py` | `GET /resolve/app/<id>`, reproducing `Controller/Sword.pm:23-103` including `autotex_log_b64` and `submission_errors`. |
| `submit_ce/sword/app.py` | App factory; routes; a non-Flask `get_session` provider for `LegacySubmitImplementation`. |

### New — ported tests

| File | Ports from | Notes |
|---|---|---|
| `submit_ce/sword/tests/client.py` | `arxiv-lib/t/lib/Test/Sword.pm` | Request builder + response parser as a pytest helper over FastAPI `TestClient`. Credentials from fixtures, never hardcoded. |
| `submit_ce/sword/tests/wrapper.py` | `arxiv-lib/t/lib/Test/Sword/Metadata.pm` | Wrapper-XML factory. **Fix** the four helper defects listed above so `comment`/`journal_ref`/`doi`/`report_no` are actually emitted correctly and therefore actually tested. |
| `submit_ce/sword/tests/conftest.py` | `arxiv-lib/t/lib/Test/DB.pm`, `t/db/sql/arXiv_sword_licenses.sql` | Fixture users mirroring `auth.t`: one fully-privileged depositor with a license, one without flags and without a license, one suspect. |
| `submit_ce/sword/tests/test_auth_gate.py` | `auth.t:20-63` | The four gate conditions and the license precondition. |
| `submit_ce/sword/tests/test_categories.py` | `03-cross.t` | All six negative cases with their exact expected substrings. |
| `submit_ce/sword/tests/test_suspect.py` | `04-suspect.t` | `EVCML`/512 + `must submit directly`, via contributor email **and** via `X-On-Behalf-Of` at the media-deposit step. |
| `submit_ce/sword/tests/test_deposit_roundtrip.py` | `02-deposit.t` | Media deposit → wrapper deposit happy path. Runs by default (no `TEST_DO_UNSAFE` gate) against mock stores. |
| `submit_ce/sword/tests/test_arxiv_elements.py` | — (new; no legacy coverage) | `comment`/`journal_ref`/`doi`/`report_no` extraction, joined with `", "` (`AtomPP.pm:1163-1168`). |
| `submit_ce/sword/tests/data/` | `t/arxiv_atompp/data/` | `sample.pdf`; plus the malformed-namespace fixture retained as a negative case for `ENPCT`. |

### Changed

| File | Lines | Change |
|---|---|---|
| `submit_ce/implementations/compile/compile_api_service.py` | 8, 121, 188, 287, 288 | Remove `from flask import current_app`; take the `SubmissionFileStore` via constructor or method parameter instead of reading `current_app.api`. **Required** — there is no Flask app context in the FastAPI process. Touches the Flask UI too, so the UI test suite must pass unchanged. |
| `submit_ce/ui/backend.py` | 27-49 | Extract `config_backend_api()` (and `email_service_from_settings`) into a framework-neutral module both apps import. Leave the Flask-specific `get_submission`/`backend_startup_health_check` helpers where they are. |
| `submit_ce/ui/config.py` | 13-30 | Make `Settings` importable without Flask; add SWORD settings (deposit bucket/prefix, retention days, 50 MB `maxUploadSize`). |
| `submit_ce/implementations/legacy_implementation/fastapi_impl.py` | 1-2 | Replace the TODO with the real non-Flask implementation supplying a plain SQLAlchemy `get_session`, mirroring `flask_impl.py:8-31`. |
| `pyproject.toml` | dependencies | Add `lxml` — Atom generation with correct namespace prefixes is painful with stdlib `xml.etree`. |
| `Dockerfile` | 88-92 | Keep the UI `CMD`; add the SWORD entrypoint so one image serves both. |
| `cicd/` | new file | Second Cloud Run service definition for the SWORD image. |

### Explicitly not changed

- `main.py` — reserved for the future modern API.
- `submit_ce/api/app.py` / `submit_ce/fastapi/` — reserved namespaces, not created here.
- `CLAUDE.md`'s `submit_ce.api.app:app` command line — left as-is per the same reservation.

### Read-only references

`arxiv-lib/lib/arXiv/AtomPP/{AtomPP,Config,Error,ServiceDoc}.pm`,
`arxiv-lib/lib/arXiv/Categories.pm`, `arxiv-lib/t/arxiv_atompp/*`,
`arxiv-lib/t/lib/Test/Sword*`, `arxiv-submit/lib/arXiv/Controller/Sword.pm`,
`arxiv-httpd/conf/sword.conf`, `arxiv-docs/source/help/submit_sword.md`.

## What this deliberately does NOT do

- **No DCSIP / Data Conservancy support.** `_process_dcsip` (`AtomPP.pm:691-838`),
  `arXiv::AtomPP::DataPub`, and the `arXiv_dcs_package` table are dead — confirmed by
  the absence of any `_ResourceMap.xml` on `lib-arxiv-039/nexus2:/data/new`.
  `X-Packaging` of the datapub type returns 415 `EMDTP`. `DataPub.pm` is not ported.
- **No `docx` deposit support.** Matching current behaviour (415). Removing it from the
  advertised media types is a separate ticket.
- **No byte-for-byte service document.** Per decision 1, each collection advertises its
  own categories, and `maxUploadSize` becomes 50000. Both change bytes clients receive.
- **No `/sword-license` in this service.** It is an HTML page under normal cookie auth
  (`sword.conf:20` has no auth block), so it belongs in the Flask UI.
- **No new auth system.** Basic auth against the existing tapir tables only; no
  keycloak/JWT path for SWORD.
- **No fork-based ingestion**, and no reproduction of the legacy no-op side effects.
- **No `ENTIT`/`ENNAM` enforcement changes** beyond what legacy does — noted as latent
  bugs, not fixed here.
- **No modern/redesigned submission API.** Out of scope by construction; the namespaces
  for it are reserved and untouched.

## Verification

1. `uv run ruff check submit_ce` is clean.
2. `uv run pytest submit_ce/api submit_ce/ui submit_ce/implementations/legacy_implementation submit_ce/implementations/file_store submit_ce/implementations/compile`
   passes — proving the `compile_api_service.py` de-Flasking did not regress the UI.
3. `uv run pytest submit_ce/sword` passes.
4. Every one of the 39 error codes renders with the right numeric code, `href`, and
   HTTP status; asserted against the table in `Config.pm:76-198`.
5. The six `03-cross.t` cases reproduce their exact expected substrings, and the
   category cap is primary + 4 secondaries (5 total OK, 6 → `ENCTS`).
6. `04-suspect.t` parity: `errorcode>512` and `must submit directly`, for both the
   contributor-email path and the `X-On-Behalf-Of`-at-media-deposit path.
7. `auth.t` parity: all four gate conditions plus the license precondition, using the
   fixture users.
8. Validation boundaries the Perl actually implements: summary length exactly 20 →
   `ENSUM` (strict `>`); `X-No-Op: false` does **not** enable no-op; `X-No-Op: True`
   creates nothing at all (decision 4).
9. MD5 accepted in both base64-with-`==` and lowercase-hex forms; mismatch → 412
   `EVMD5`.
10. Namespace assertion: rendered XML contains `http://arxiv.org/terms/arXiv/`, never
    the `https://` variant — the exact check
    `arxiv-test-regression/pytest/tests/test_sword.py:67-68` makes. The malformed-namespace
    fixture yields `ENPCT`.
11. A 50 MB deposit succeeds; the service document advertises `50000`.
12. Round-trip integration test: servicedocument → zip media deposit (201, `Location`,
    parseable `info:arxiv/app/<id>`) → wrapper POST (202) → `GET /resolve/app/<id>`
    returns `<deposit><status>`. A deposit that fails to compile surfaces
    `submission_errors` (decision 6).
13. Confirm the created submission is indistinguishable from a UI submission: same
    event stream shape, `proxy` set to the depositor, `sword_id` populated on
    `arXiv_submissions`.
14. Point `arxiv-test-regression/pytest/tests/test_sword.py` and `test_sword_gcp.py` at
    the new service; both pass unmodified. **This is the acceptance gate.**
15. Verify the UI and SWORD Cloud Run services deploy from the same image and neither
    can serve the other's routes.

## Suggested order of implementation

Ordered so each step is verifiable and the risky shared-code change lands first,
while the UI test suite can still catch it.

1. **De-Flask `compile_api_service.py`.** Smallest change with the widest blast
   radius; do it alone and confirm the full existing suite passes (verify: step 2).
2. **Extract backend wiring and config out of `ui/`**; UI keeps working via the
   extracted module (verify: step 2).
3. **Non-Flask `get_session` + `fastapi_impl.py`**; prove a `SubmitApi` can be built
   and used with no Flask app context (verify: a unit test calling
   `save(CreateSubmission(...))` outside Flask).
4. **`errors.py` + `atom/ns.py` + `atom/render.py`** — pure functions, no I/O
   (verify: steps 4, 10).
5. **Test scaffolding**: `conftest.py` fixtures, `client.py`, `wrapper.py` — ported
   from `Test::Sword*` with the four helper defects fixed. Landing this before the
   endpoints means every later step has its assertions ready.
6. **`auth.py` + `collections.py`** and a FastAPI app serving only
   `GET /servicedocument` (verify: steps 7, 11).
7. **`deposits.py`** — staging store and id allocator, with a concurrency test on the
   compare-and-swap.
8. **Media deposit POST** → 201 (verify: `test_deposit_roundtrip` media half; the
   `X-On-Behalf-Of` suspect case from step 6).
9. **`atom/parse.py`** — the validation ladder, unit-tested exhaustively before it is
   wired to anything (verify: steps 5, 8, and the new `test_arxiv_elements`).
10. **`ingest.py`** — wrapper POST → events → 202 + tracking row (verify: steps 12, 13).
11. **`tracking.py`** — `/resolve/app/<id>` (verify: step 12 complete).
12. **GET `getid`/`edit`, PUT replacement, DELETE/405 paths** — the remaining verbs.
13. **`/sword-license` in the Flask UI** (verify: `test_toggle_default_license` passes).
14. **Dockerfile entrypoint + second Cloud Run service** (verify: step 15).
15. **Full regression suite against a deployed dev instance** (verify: step 14).

Steps 1–3 are prerequisites with no SWORD-visible behaviour and can be reviewed
independently — worth landing as their own PR.

## Summary of working the plan

**Steps 1–3 complete and verified** (2026-07-30) — the prerequisite refactors with no
SWORD-visible behaviour, which the plan flagged as worth their own PR. Steps 4 onward
not started.

### Step 1 — de-Flask `compile_api_service.py` ✅

Smaller than planned. All three methods that read `current_app.api` **already received
`api: SubmitApi` as a parameter** (`compile_api_service.py:99,184,282`), and all three
call sites in `domain/event/process.py:64,108,387` already pass it. So the change was a
pure substitution of `current_app.api` → `api`, plus deleting the import — no
constructor or signature change.

`submit_ce/implementations/tests/test_compile_api_service.py` needed updating: it
patched `compile_api_service.current_app`, which no longer exists. Replaced the
`_patch_current_app` helper with `_mock_api(store)`, passed as the `api` argument the
methods already accept. Net −9 lines in the test.

### Step 2 — extract wiring out of `ui/` ✅

New `submit_ce/implementations/wiring.py` holds `config_backend_api` and
`email_service_from_settings`, moved verbatim from `ui/backend.py`. It imports no
Flask and no `submit_ce.ui` — the type hint was already `arxiv.config.Settings`, not
submit-ce's subclass.

Only two consumers existed, both updated: `ui/factory.py:36` and
`ui/tests/test_backend_email_service.py` (import + three `mock.patch` targets). No
compatibility shim was added. `ui/backend.py` lost 64 lines including twelve
now-orphaned imports and its unused `logger`; `ui/factory.py` lost its `backend`
import, which ruff caught.

**Config extraction turned out to be unnecessary.** The plan assumed `Settings` had to
come out of `ui/`, but `submit_ce/ui/config.py` and `submit_ce/ui/__init__.py` import
no Flask (only `re`, `arxiv.auth.domain.Session`, `markupsafe.Markup`), so
`from submit_ce.ui.config import settings` is already safe from a non-Flask process.
That part of the planned change was dropped.

### Step 3 — non-Flask `SubmitApi` ✅

The key discovery is in `arxiv-base`: `arxiv.db.Session` is a `scoped_session` whose
`scopefunc` returns the Flask app-context id **when one exists and the current thread
id otherwise** (`arxiv-base/arxiv/db/__init__.py:88-94`). So the existing session
registry already works outside Flask; the old `fastapi_impl.py` TODO was right that
"nothing is stopping anyone from using the LegacySubmitImplementation with fastapi".

What that scoping does *not* provide is teardown. The Flask app calls
`Session.remove()` in `teardown_appcontext` (`ui/factory.py:66-68`); without an
equivalent, a threadpool thread's session leaks into the next request on that thread.
So `fastapi_impl.py` now provides `fastapi_get_session()`, `remove_session()`, and a
thin `FastapiSubmitImplementation`, with the constraint documented: **endpoints
touching the `SubmitApi` must be `def`, not `async def`**, because `async def` handlers
share the event-loop thread and would share one session across concurrent requests.

`config_backend_api` gained an `impl` parameter defaulting to
`FlaskSubmitImplementation`, so the UI is unchanged and the SWORD service passes the
FastAPI one. `get_session()` is called repeatedly per `save()`
(`legacy_implementation/__init__.py:109,113,117,149,365,401,425`), including as a
context manager, so the provider must return a *consistent* session — a
`session_factory()`-per-call provider would have split one save across transactions.
There is a test pinning this.

New `submit_ce/implementations/legacy_implementation/tests/test_fastapi_impl.py` (5
tests): `save(CreateSubmission(...))` with `has_app_context()` false throughout,
`get_with_history` round-trip, session stability within a scope, `remove_session`
starting a fresh session, and per-thread scoping.

### Verification status

- Dockerfile CI gate (`pytest submit_ce/api submit_ce/ui
  submit_ce/implementations/legacy_implementation/ submit_ce/implementations/file_store/
  submit_ce/implementations/compile`): **189 passed, 57 skipped**.
- Wider run (adds `submit_ce/domain`, `submit_ce/implementations`): **535 passed, 57
  skipped** — 530 pre-change plus the 5 new tests.
- `ruff check` clean on every file touched.
- All 57 skips are pre-existing GCS integration tests gated on
  `TEST_GS_FILE_STORE_AT_GCP=1`.

### Incidental findings (not fixed)

1. `submit_ce/implementations/legacy_implementation/tests/` was the **only** test
   directory in the package without `__init__.py`, so neither it nor the pre-existing
   `test_save_proxy.py` could be run standalone (`ModuleNotFoundError: submit_ce`).
   Added the empty `__init__.py` since the new test lives there; both now run in
   isolation.
2. **`submission_id` type inconsistency:** `save()` returns it as `int`,
   `get_with_history()` as `str`. Worked around in the new test with a comment; not
   fixed. Likely to matter for SWORD, which must put this value into
   `arXiv_tracking.paper_id` as `submit/<submission_id>`.
3. Three pre-existing `ruff` errors in files not touched here:
   `domain/event/email_mods.py:23` (unused `pydantic.Field`) and
   `implementations/email/tests/test_halon_email.py:5,220` (unused then redefined
   `pytest`).
4. One transient failure was observed in `submit_ce/implementations/pubsub/tests/`
   reaching real GCP over gRPC; it did not reproduce in three consecutive runs and is
   unrelated to these changes. Those tests need `PUBSUB_EMULATOR_HOST`.

### Test-safety guards (added 2026-07-31, before step 4)

Verified first that the suite was already clean: with all non-loopback TCP blocked,
`test.sh` passed unchanged and attempted **zero** outbound connections. Email is
`EmailInMemory` by default, `smtplib` is mocked, Secret Manager is never called, and
`QA_PUBSUB_ENABLED` is pinned off in the `app` fixture. The default QA topic is in
**arxiv-development**, not production.

Three latent holes were closed, because "nothing currently escapes" is not the same as
"nothing can" — and the SWORD tests are about to be written against the same harness:

1. New repo-root `conftest.py` pins `EMAIL_MODE=TESTING`, `QA_PUBSUB_ENABLED=False`,
   `STORE=null` and `COMPILE_API_URL=http://localhost:0`. The last one matters twice
   over: the default is a live Cloud Run URL that no test pins, and an `https://` URL
   also makes `compile_api_service._auth_headers` mint a real GCP ID token.
2. The same conftest blocks non-loopback TCP for the whole suite, with
   `@pytest.mark.allow_network` as the opt-out. Loopback stays open so sqlite and the
   Pub/Sub emulator work.
3. `submit_ce/tests/test_guards.py` (5 tests) asserts the guards actually hold, so they
   cannot rot silently. Added `submit_ce/tests` to `test.sh`; CI collects it already.

The Pub/Sub emulator fixture was also repaired: it bound `[::1]` while advertising
`PUBSUB_EMULATOR_HOST=localhost`, leaving reachability to the client's name resolution —
the likeliest cause of the transient gRPC retry failure noted above (which was **not**
a real-GCP call; `PUBSUB_EMULATOR_HOST` forces anonymous credentials). It now binds
`localhost`, starts once per session instead of per test, allocates its port once, and
**skips** rather than errors when gcloud or the emulator component is missing. Topic and
subscription names are per-test, since a session-scoped emulator retains resources
between tests. Result: 4 passed in 3.1s (was 5.7s), and 4 clean skips in 0.07s when
gcloud is absent.

**Implication for step 5:** SWORD tests inherit these guards, so the media-deposit
staging store and the `sword_id` allocator must be testable against a fake or an
emulator — a real GCS client will be blocked, not silently exercised.

### Step 4 — errors and error rendering ✅ (2026-07-31)

Also added ahead of it, at the user's request: `local_sword.py` plus a minimal
`submit_ce/sword/app.py` (factory, `db.init`, non-Flask `SubmitApi` on
`app.state.api`, one I/O-free `GET /status`). Verified running: `/status` → `ok`
200 on port 8001, alongside `local_ui.py` on 8000.

- `submit_ce/sword/atom/ns.py` — namespaces, schemes, versions. All `http://`.
- `submit_ce/sword/errors.py` — all 39 codes with message, href and default HTTP
  status, plus a `SwordFault` exception carrying the `": detail"` summary suffix.
- `submit_ce/sword/atom/render.py` — `render_error()` producing the
  `<sword:error>` document, with injectable timestamp/id for determinism.
- 80 tests in `submit_ce/sword/tests/`, including an independently transcribed
  mnemonic→code table, and the exact substrings `03-cross.t` and `04-suspect.t`
  assert on. Added `submit_ce/sword` to `test.sh`.
- `lxml` added as a dependency: it gives per-tree `nsmap` control, so the root
  `<sword:error>` can sit in the sword namespace while its children default to
  Atom, without `ElementTree.register_namespace`'s process-global state.

Two deliberate deviations from legacy, both documented in the code:

1. **Fresh UUID per error.** The Perl builds a name-based UUID from constant
   inputs (`Error.pm:57`), so every legacy error carries an identical id — useless
   for correlating a client report with a log line, and contradicted by the
   manual's own varying examples.
2. **`sword:packaging` / `sword:userAgent` omitted** from error documents, per
   discrepancy 8 above.

Deferred to the steps that produce them: the service document and the deposit
response entries, both of which need collection and deposit data that does not
exist yet.

**Environment note:** `uv add lxml` re-synced the venv and pruned `ruff`, which is
not a declared dependency (`lint.sh` installs it ad hoc). Reinstalling brought
ruff 0.16.1, whose default rule set now includes pyupgrade; `./lint.sh` therefore
reports ~1264 findings across the package, almost all `UP045` (`Optional[X]`) and
`UP017` (`timezone.utc`) on pre-existing code. Under the rule set the repo was
previously clean against (`--select E4,E7,E9,F`) every new file passes and the
package still shows only the 3 known pre-existing errors. Worth pinning ruff in
`[dependency-groups] dev` to stop this drifting again.

### Step 5 — test scaffolding ✅ (2026-07-31)

Ported from the Perl helpers, landed before the endpoints so later steps have
their assertions ready.

- `submit_ce/sword/tests/wrapper.py` — wrapper-entry builder replacing
  `Test::Sword::Metadata.pm`, with all five helper defects fixed, plus
  `malformed_namespace_entry()` reproducing `data/sample.xml`'s broken namespace
  as a deliberate ENPCT negative fixture.
- `submit_ce/sword/tests/client.py` — depositor client replacing
  `Test::Sword.pm`: `content_md5`/`content_md5_hex`, `deposit_headers`,
  `basic_auth`, response-link extractors, and a `SwordClient` over any
  httpx-shaped object. No hardcoded credentials.
- `submit_ce/sword/tests/conftest.py` — four depositor fixtures on a
  function-scoped sqlite database: `depositor` (privileged + licensed),
  `unlicensed_depositor` (privileged, no license → isolates 412 ENLIC from 401
  EAUTH), `plain_user` (neither flag), `suspect_author` (`flag_suspect`).
- 55 new tests (`test_wrapper.py`, `test_client.py`, `test_depositors.py`),
  bringing the suite to 675.

Request construction is tested against a recording stub rather than a live app,
so all of it passes before any route exists. `test_depositors.py` pins the
fixtures against what `auth.t` asserts, so the authorization step cannot pass for
the wrong reason.

Two findings:

1. **`SwordLicense.updated` must be supplied explicitly on sqlite.** It is
   `NOT NULL` with `server_default=FetchedValue()`, which is a marker meaning "the
   database provides this" rather than DDL — MySQL fills it from
   `CURRENT_TIMESTAMP`, but `create_all` on sqlite emits no default and the insert
   fails. Expect the same for other `FetchedValue()` NOT NULL columns as later
   steps write more tables.
2. **A fifth defect in `Test::Sword::Metadata.pm`** (recorded above):
   `arxiv:affiliation` was never emitted, so the affiliation path was untested too.

Also corrected in passing: an assertion of mine that read
`check_password(...) is not False`, which is vacuous — `check_password` returns
`True` or raises `PasswordAuthenticationFailed`. Now asserts both directions.

### Step 6 — auth, collections, service document ✅ (2026-07-31)

- `submit_ce/sword/auth.py` — the three gates in legacy's order: Basic credentials,
  then `flag_xml`/`flag_proxy`/`veto_status`/`flag_banned`, then the
  `arXiv_sword_licenses` precondition. Plus `is_suspect_email` for `04-suspect.t`.
- `submit_ce/sword/collections.py` — collection↔group mapping, `flag_group_*`
  permissions, and per-collection category terms off `arxiv.taxonomy`.
- `submit_ce/sword/atom/servicedoc.py` — the service document.
- `GET /sword-app/servicedocument` wired in `app.py`, with a `SwordFault`
  exception handler that renders `sword:error`, and the 405 method whitelist.
- 90 new tests; suite now 765 passed, coverage 82.14%.

**Password verification is new code.** Legacy never checked credentials in-process
— Apache did, via `mod_authnz_external` → `cgi-bin/authenticate.pl`
(`sword.conf:10-13`), so the CGI trusted `REMOTE_USER`. Now done against
`arxiv.auth.legacy.passwords.check_password`.

Deliberate differences, each documented at its call site:

1. **A no-groups depositor gets an empty workspace.** `ServiceDoc.pm:104-107`
   defaulted to *every* group with a warning, advertising collections the
   depositor cannot post to.
2. **Collection permission is an exact match.** `AtomPP.pm:222` used a regex, so
   `c` matched `grp_cs` by substring.
3. **A 401 carries a `sword:error` body plus `WWW-Authenticate`**, where legacy
   returned Apache's stock HTML page. Every other failure is already a
   `sword:error`, and the challenge header is what makes a client re-prompt.
4. **`maxUploadSize` is derived from `SIZE_LIMIT_POLICY`** — 51200 kB. Legacy
   hardcoded 10000 while its real cap was `CGI::POST_MAX` of 10 MiB (10240 kB),
   so it under-advertised even its own limit.
5. **`acceptPackaging` offers zip only**; the Data Conservancy packaging is dead
   (decision 2) and now answers 415, so advertising it would be a lie.

Three taxonomy findings:

1. **Every `test` category is flagged inactive** in `arxiv.taxonomy`, so
   `Archive.get_categories()` returns nothing for the `test` archive — which would
   have silently produced a test collection with no categories and failed the
   live regression assertion for `test.dis-nn`
   (`arxiv-test-regression/pytest/tests/test_sword.py:67`). `include_inactive` is
   used for `grp_test` only.
2. **`grp_bad` must be excluded** — it is a synthetic marker for unresolvable
   archives and has no `flag_group_bad` column, so it could never be granted.
   There is a test asserting every listed group *does* have a flag column.
3. **`flag_group_nlin` is vestigial.** The column still exists on
   `arXiv_demographics`, but there is no `grp_nlin` in the taxonomy — nlin was
   folded into physics in 2012-12 (`submit_sword.md:1070-1077`). Nothing reads it.

Also: `submit_ce/sword/tests/conftest.py` now repoints `settings.CLASSIC_DB_URI`
at the fixture database, because `create_sword_app` builds its *own* engine from
settings (`config_backend_api` → `configure_db` → `session_factory.configure`).
Without that the app under test would quietly read the repo's checked-in
`legacy.db`. This is also why the fixture uses a file rather than `:memory:` — two
engines have to see the same schema.

### Step 7 — deposit staging store and id allocator ✅ (2026-07-31)

- `submit_ce/sword/deposits.py` — `DepositStore` (abstract, with the allocation
  retry loop shared by every backend), `InMemoryDepositStore`, the media-type →
  extension mapping, and the `YYMM####` id format.
- `submit_ce/sword/gs_deposits.py` — `GsDepositStore`, mirroring legacy's
  `/cache/atomdeposits` tree onto a bucket, with `flock` replaced by
  `if_generation_match` on the counter object.
- 75 new tests; suite now 840 passed. **The whole `submit_ce/sword` package is at
  100% statement and branch coverage.**

Notable points:

1. **The GCS backend is fully tested, not coverage-omitted.** `GsDepositStore`
   takes an injectable `client` the way `GsFileStore` does, so a fake bucket that
   tracks generations and raises `PreconditionFailed` exercises the whole
   conditional-write path — including a competing writer landing between our read
   and our write, and permanent contention producing ENAVL. Its sibling
   `gs_file_store.py` is in the coverage `omit` list; this one did not need to be.
2. **Legacy expresses the extension mapping twice and the two agree.** A
   content-type dispatch table for storing (`AtomPP.pm:262-274`) and a MIME-subtype
   rule for resolving wrapper links (`AtomPP.pm:1109-1116`) produce identical
   results for every supported type, so one function serves both. They were free
   to drift; now they cannot.
3. **Ownership is recorded explicitly** (GCS object metadata) rather than
   recovered by re-parsing the `.atom` sidecar's `<author><name>` as legacy does
   (`AtomPP.pm:379,1124-1129`). One authoritative field beats re-deriving it from a
   document we also generate.
4. **`Group.get_archives()` already excludes defunct archives**, which is exactly
   the `%IN_GROUP_NOT_DEFUNCT` set `ServiceDoc.pm:189` iterated. An explicit
   `is_active` filter in `collections.py` was therefore dead code and was removed;
   the behaviour is asserted instead (there are 18 defunct archives — `acc-phys`,
   `chao-dyn`, `q-alg`, `supr-con` and more).
5. **ENAVL, not a crash, on allocation failure.** Exhausting the retry budget
   raises `SwordFault("ENAVL")` → 503, which is what legacy answers when it cannot
   take the counter lock (`AtomPP.pm:256-260`).

Retention (≥30 days) is left to a bucket lifecycle rule rather than application
code; nothing here purges.

### Step 8 — media deposit ✅ (2026-07-31)

`POST /sword-app/<collection>-collection` → 201 with a media link entry.

- `submit_ce/sword/request.py` — SWORD header parsing (`X-On-Behalf-Of`,
  `X-Verbose`, `X-No-Op`, `X-Packaging`, `Content-Disposition`) and `Content-MD5`
  verification in both encodings.
- `render_media_entry` in `atom/render.py` — output matches
  `submit_sword.md:909-931` element for element, differing only in the two already
  documented ways (`http://` namespaces, generator `1.1`).
- The route, plus `build_deposit_store` selecting GCS or in-memory from `STORE`.
- 92 new tests; suite now 928 passed. `submit_ce/sword` remains at **100%**
  statement and branch coverage.

`02-deposit.t`'s media half and the live suite's `test_paper_upload` now run
in-process against mock stores instead of only against a deployed service. So does
`04-suspect.t`'s second case — a flagged contact author is refused at the **media**
step, because `process_sword_headers` runs on media POSTs too
(`AtomPP.pm:885-890`).

**A tenth docs/code discrepancy, and it changes behaviour.** The manual documents
an unknown collection as EVCOL with `invalid collection: foobar`
(`submit_sword.md:845-875`), but legacy cannot produce that: it tests group
permission *first*, with `grep {/$group/}` over the user's `grp_*` names
(`AtomPP.pm:222`), and no bogus collection name matches any of them — so an unknown
collection answers **EAUTH**, and the documented EVCOL example is unreachable.
Implemented as documented: unknown collection → EVCOL, known-but-not-permitted →
EAUTH. That also drops legacy's substring matching, under which `c` would have
matched `grp_cs`.

Two further deliberate differences:

1. **RFC 2606 reserved domains are refused** in `X-On-Behalf-Of`
   (`.invalid`, `.localhost`, `.test`). `Email::Valid->address` is syntax-only, so
   legacy accepted them. The contact address exists so arXiv can send the
   identifier and paper password (`submit_sword.md:68-72`); accepting an address
   that provably cannot receive mail guarantees that never arrives. Deliverability
   is *not* checked — that would put a DNS query in every deposit.
2. **`X-Packaging: …dataconservancy.org/package` is refused** (415) rather than
   accepted-then-failed-deeper-in, since its handler is out of scope (decision 2).
   `mets/dspace` was already refused: `Config.pm:201` maps it to `0`, which
   `AtomPP.pm:907` treats as unsupported.

Faithfully reproduced quirks: `X-No-Op` is enabled by *any* value except the
literal `false`, so an empty-but-present header switches it on
(`AtomPP.pm:896-901`); a no-op deposit answers 200 and sends no `Location`; and
`Content-Disposition` is parsed only to be echoed back.

One implementation note: request bodies arrive as a declared `bytes` parameter, not
via `await request.body()`. A sync endpoint cannot await, and driving the coroutine
on a private event loop — which I tried first — is wrong, because Starlette's
`receive()` is bound to the serving loop. FastAPI reads the body on the event loop
before dispatching to the threadpool.

Wrapper deposits (`application/atom+xml`) currently answer 501 with an explicit
"not yet available"; step 10 replaces that.

### Step 9 — wrapper validation ladder ✅ (2026-07-31)

`submit_ce/sword/atom/parse.py` — `parse_wrapper()` returning a validated
`WrapperMetadata`, plus 77 tests. Suite now **1005 passed**; `submit_ce/sword`
back to **100%** statement and branch coverage. Not yet wired to a route; step 10
does that.

Deliberately I/O-free so the whole ladder is unit-testable: `is_suspect_email`,
`deposit_extensions` and `deposit_owner` are injected callables. Check order is
legacy's and is asserted — categories are validated **before** the summary, so a
wrapper wrong in both ways reports the category error.

All six `03-cross.t` cases now pass against real parsing, matching the exact
substrings that suite greps for, as do `04-suspect.t`'s error code 512 and "must
submit directly".

**`is_valid_category_strict` needed real care.** The naive mapping — "is it in
`CATEGORIES`?" — is wrong in both directions:

* `cond-mat` **is** in `CATEGORIES` (inactive), yet `03-cross.t:358-362` requires
  it to be rejected.
* `test.dis-nn` is **also** inactive, yet it must be accepted — it is what the test
  collection deposits.

So active/inactive is not the discriminator. The rule that reproduces legacy
(`Categories.pm:1164-1178`) is: a dotted id must exist; a **bare archive name is
valid only when that archive has no subject classes**. `cond-mat` has
`cond-mat.*`, so bare is invalid; `hep-ex` has only itself, so bare is fine.
Verified against 14 cases before writing a line of the parser.

**One security fix, worth a decision.** Legacy checks whether a referenced media
deposit belongs to the depositor, then only `carp`s about it — with
`## FIXME: this should be fatal` on the next line (`AtomPP.pm:1126-1129`). Without
enforcement a depositor can attach *another user's* staged files to their own
submission. `parse_wrapper` raises ENOWN instead. This is a behaviour change from
legacy, and the one place in this port where I have deliberately closed a
vulnerability rather than reproduced it.

**Two unreachable paths identified, one removed.** After the `rel="related"` loop,
legacy does `if (@files) {...} else { ENMDE }` (`AtomPP.pm:1156-1161`) — but every
related link either errors out or appends a file, so the list is non-empty whenever
the count is. The branch cannot be reached in legacy either. Not reproduced; ENMDE
stays in the error table for completeness but has no live caller. (`ENTIT` is the
other: defined, documented, never raised, because `AtomPP.pm:1183` reads
`$entry->title()` unchecked. An untitled wrapper is accepted, and there is a test
pinning that.)

Also confirmed against the code rather than the manual: the primary-category term
regex allows no digits (`AtomPP.pm:980`), which is safe only because no arXiv
category id contains one; and the secondary-term regex is *unanchored*
(`AtomPP.pm:1018`), so it extracts a category from anywhere in the attribute.

### Step 10 — wrapper deposit and ingest ✅ (2026-07-31)

A metadata wrapper POST now creates a real submission and answers 202.

- `submit_ce/sword/ingest.py` — `metadata_events()` / `upload_events()` (pure,
  over a `WrapperMetadata`), `record_tracking()`, and `ingest_wrapper()`.
- `render_wrapper_entry` in `atom/render.py` — the 202 body, with the
  `rel="alternate"` tracking link.
- The wrapper branch of the collection POST route.
- 68 new tests; suite now **1058 passed**, `submit_ce/sword` back to **100%**
  statement and branch coverage.

`02-deposit.t`'s second half and the live suite's `test_metadata_upload` now run
in-process. The tests assert on *submission state*, not just the response document:
title, abstract, authors, proxy, contact, license, categories and both tracking
links.

Everything goes through a **single `SubmitApi.save()`**, so a deposit is one
transaction — a validation failure anywhere leaves no partial submission, which
there is a test for.

**One event covers three legacy columns.** `SetProxyInformation` sets
`proxied_name`/`proxied_email` → `submission.creator.name`/`.email` → legacy
`submitter_name`/`submitter_email`, and `proxy_name` → `proxy`. That is exactly what
legacy SWORD wrote (`AtomPP.pm:1193-1195`), so the plan's separate
`ConfirmContactInformation` row turned out to be unnecessary.

**The endorsement gate needed a decision.** `SetPrimaryClassification` requires the
creator to be endorsed for the category (`domain/event/__init__.py:311-323`); legacy
SWORD has no such check, because deposit permission *is* the `flag_group_*` bit,
granted per collection by arXiv admins alongside `flag_xml`/`flag_proxy`. Requiring
personal endorsements as well would be stricter than legacy and would break exactly
the proxy depositors — conference organisers, journal editors — that `flag_proxy`
exists for. So `collections.endorsement_wildcards()` turns each permitted group into
`<archive>.*` for its archives: the same permission, in the vocabulary the events
understand. `AddSecondaryClassification` is not endorsement-checked at all, so
cross-listing outside a depositor's groups still works, as in legacy.

**`ConfirmPolicy` is emitted on the depositor's behalf.** `FinalizeSubmission`
requires `submitter_accepts_policy`, and SWORD has no interactive agreement step.
Acceptance rests on what the protocol already requires out of band: admin
authorisation (`submit_sword.md:98-101`) and a registered default license
(`:122-127`), the latter a hard precondition of every request.

Also of note: a zip becomes `UploadArchive` so it is unpacked, while loose files
(PDF, figures) become one `UploadFiles` — the two shapes the manual describes
(`submit_sword.md:317`). `X-No-Op` is a true no-op: validated, reported on, nothing
created, and there is a test asserting neither a submission nor a tracking row
appears.

Two things still deferred, both requiring compile:

1. **`SetSourceFormat` + `FinalizeSubmission`.** `source_format` only comes from
   preflight, so finalizing stays on the async compile path.
2. **`test.*` categories are all flagged inactive**, and both
   `SetPrimaryClassification` and `AddSecondaryClassification` validate against
   `ActiveCategory`. A deposit to the `test` collection will therefore be rejected
   by the domain even though the service document advertises it and the live
   regression suite uses it on non-dev environments. Needs resolving before the
   acceptance gate — either the taxonomy's `test` entries change, or the events need
   to accept them.

### Step 11 — deposit tracking ✅ (2026-07-31)

`GET /resolve/app/<sword_id>` in `submit_ce/sword/tracking.py`, answering the
`rel="alternate"` link a wrapper deposit hands back. 25 new tests; suite now
**1083 passed**, `submit_ce/sword` at **100%** statement and branch coverage.

Output matches the manual's examples (`submit_sword.md:668-681`) structurally, and
tracking works the instant a client receives its 202 — which is the payoff for
writing the tracking row synchronously in step 10 rather than in a forked child.

**Unauthenticated, deliberately.** `sword.conf` puts `/sword-app` and `/ppw` behind
basic auth but not `/resolve`, which is served by the Catalyst app, and the manual
documents a plain GET (`submit_sword.md:664`). Reproduced as-is — worth knowing this
means deposit status is world-readable to anyone who can guess a deposit id, since
ids are near-sequential.

**An eleventh discrepancy: a sixth status.** The manual defines five —
`submitted`, `published`, `on hold`, `incomplete`, `unknown`
(`submit_sword.md:686-706`) — but `Controller/Sword.pm:49-52` also emits **`failed`**
with "conflicting submission active" when the tracking row's `paper_id` contains
`failed`. Reproduced, since a client that has seen it may switch on it.

Status mapping onto submit-ce's model, with `on hold` taking precedence because a
held submission is still `SUBMITTED` there with the hold recorded separately:

| submit-ce | SWORD |
|---|---|
| `is_announced` | `published` |
| `is_on_hold` | `on hold` |
| `is_finalized` | `submitted` |
| otherwise | `incomplete` |

The manual says `incomplete` is "not expected to be used for SWORD submissions"
(`:700-702`). That is now reachable, because finalization waits on preflight — a
deposit sits in `incomplete` between its 202 and a successful compile.

Two smaller notes:

* **Element order is fixed here.** Legacy iterates a Perl hash with `each`
  (`Controller/Sword.pm:96-100`), so its order varies between responses; no client
  can depend on it, which makes a stable order strictly safer.
* **`tracking_id` uses `http://`**, matching the `alternate` link the deposit
  response emits (`AtomPP.pm:1480`). The manual renders it `https`, but the manual's
  schemes are unreliable throughout (discrepancy 1), and Catalyst's `uri_for` would
  simply follow the request scheme.

The undocumented `autotex_log_b64` extension (`Controller/Sword.pm:36-56`) is
carried over, reading the compile log best-effort and omitting the field on any
failure, as the Perl's try/catch does. Note `MockFileStore` inherits
`NullFileStore`'s compile-log stubs — `does_compile_log_exist` is always False — so
that path needs a purpose-built fake rather than the usual test store.

Routes now registered: `/status`, `/sword-app/servicedocument`,
`POST /sword-app/{collection}-collection`, `/resolve/app/{sword_id}`.

### The `test` collection: root cause and fix ✅ (2026-07-31)

Steps 6 and 10 flagged that every `test.*` category is `is_active=False`, so the
domain rejected deposits to the `test` collection even though the service document
advertises it and the live regression suite uses it. Two things were wrong in how I
first described this.

**It was never SWORD-specific.** The gate is
`validators.must_be_an_active_category`, called by both `SetPrimaryClassification`
and `AddSecondaryClassification`. No user with `flag_group_test` could make a test
submission through the **Flask UI** either. (`ActiveCategory` in
`domain/event/__init__.py:109-111` is inert — the annotated validator is commented
out and it is just `str`.)

**Root cause: `arxiv.taxonomy`'s `is_active` does two jobs.** The legacy Perl keeps
them apart:

* **Validity** comes from `%Subj_class_name`, where the test subject classes are
  ordinary entries (`arxiv-lib/lib/arXiv/Config/SubjectClasses.pm:385-399`). That
  structure has **no notion of "active" at all** — `is_valid_category_strict` only
  ever asks "does this subject class exist?"
* **Listing** comes from `%IN_GROUP_NOT_DEFUNCT`, which deletes `test` **by name**
  alongside the genuinely defunct archives
  (`arxiv-lib/lib/arXiv/Config/Archives.pm:346-352`). Callers that want it add it
  back explicitly, which is exactly what `ServiceDoc.pm:189` does with
  `sort keys %IN_GROUP_NOT_DEFUNCT, 'test'`.
* **Permission** is `flag_group_test`, mapped to the `test` group at
  `UserExt.pm:161` — already handled by `collections.endorsement_wildcards`.

So the live suite works because legacy never asks whether a category is active.
arxiv-base collapsed "hidden from listings" into "not a valid category", and
`test.*` needs *valid but not listed* — which one boolean cannot express.

**Fix:** `is_submittable_category` in `submit_ce/domain/event/validators.py` accepts
an inactive category when it is a subdivided category of the `test` archive.
`test` is **named**, not inferred from a rule like "inactive category in an active
archive", for the same reason the Perl names it: today `test` is the only archive of
that shape, but retiring a real category while its archive stayed active would
silently make it submittable again. A test asserts that narrowness and fails if the
taxonomy ever grows another such archive without this being revisited.

Bare `test` stays invalid — the archive requires a subject class
(`$Subj_class_required{'test'} = 1`).

33 new tests (`domain/event/tests/test_submittable_category.py`, plus an end-to-end
`test` collection deposit and a bare-`test` rejection in the SWORD suite). Suite now
**1116 passed**. This unblocks the acceptance gate and fixes the UI path at the same
time.

### Remaining items to watch

1. **Finalize sequencing.** The plan finalizes after a successful compile. The exact
   trigger (FastAPI background task vs. hooking submit-ce's existing async compile/QA
   path) should be chosen when step 10 is built, once the non-Flask `SubmitApi` from
   step 3 is exercised in practice.
2. **`is_valid_category_strict` bare-archive parity.** `arxiv.taxonomy` gives
   `is_general`, `in_archive`, canonicalization and group lookup directly, but the
   "bare archive name valid only if no subject class required" rule
   (`Categories.pm:1168-1174`) has no single arxiv-base equivalent and will need
   explicit handling — this is what makes `cond-mat` invalid in `03-cross.t`.
