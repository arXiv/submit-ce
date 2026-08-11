# SWORD API code review — SUBMISSION-29

Review of `develop..SUBMISSION-29-sword` at `a680dfb` (2026-08-04).
Scope: 77 files, +11,944 / −147. No PR open at time of review, so the range was
diffed locally.

Companion documents: [the implementation plan](20260730-plan.md),
[security review](20260804-security-review.md),
[design review](20260810-design-review.md), and the
[manual testing guide](../../sword-getting-started.md).

Findings are ordered by severity. Each one records the evidence it rests on,
because several plausible-looking concerns turned out to be non-issues on
investigation and are listed as such at the end — they should not be
re-litigated.

## Summary

| # | Severity | Finding | Area | Status |
|---|----------|---------|------|--------|
| 1 | High | Only `SwordFault` has an exception handler; everything else is a non-XML 500 | `sword/app.py` | **Fixed** |
| 2 | High | `announced_submission_id()` ignores announced status; no conflict detection | `sword/replace.py` | **Fixed** |
| 3 | High | `/sword-license` POST has no CSRF token, against repo convention | `ui/` | **Fixed** |
| 4 | Medium | Wrapper deposits are not size-capped before parsing — a regression from legacy's `$CGI::POST_MAX` | `sword/deposits.py` | **Fixed** |
| 5 | Medium | Oversize deposits answer 415 with a self-contradicting error document | `sword/errors.py` | **Fixed** |
| 6 | Medium | Advertised 50 MB `maxUploadSize` may exceed the Cloud Run request limit | `cicd/` | Open |
| 7 | Medium | `/docs`, `/redoc`, `/openapi.json` served publicly | `sword/app.py` | **Fixed** |
| 8 | Medium | GCS id counter is a single-object write hotspot | `sword/gs_deposits.py` | Accepted |
| 9 | Low | Socket test guard does not stop gRPC, and its docstring claims it does | `conftest.py` | Open |
| 10 | Low | Assorted docstring/robustness nits | various | Open |
| 11 | High | A replacement's new row gets no event rows, so it cannot be loaded | `legacy_implementation/db.py` | Open, pinned |
| 12 | Medium | A malformed CSRF token is a 500 from `arxiv.forms.csrf` | `arxiv-base` | Worked around |
| 13 | — | `arxiv.forms.csrf` is documented "DO NOT USE" | `arxiv-base` | Accepted |

Findings 11–13 were turned up by fixing 1–3, and 11 is the most serious thing in
this document. Two claims in the first revision were wrong; see
[Corrections](#corrections-to-the-first-revision).

## What is strong

Worth recording so it survives future refactors:

- **Every deviation from the Perl carries a `file:line` citation.** This is what
  made the review tractable at all, and it is the single most valuable property
  of the branch. Preserve it.
- **608 tests at 100% statement and branch coverage** on `submit_ce/sword`, and
  the tests are mostly specific rather than smoke tests.
- **`db.py:492` fixes a real pre-existing bug** — `_create_replacement` omitted
  `remote_addr`/`remote_host`, silently losing the depositor's address on MySQL
  and failing the insert on a backend without the DDL default. Affects the
  Flask UI's replacement flow too, not just SWORD.
- **`is_submittable_category` argues why `test` is named rather than inferred**
  from a rule like "inactive category in an active archive". Correct call, and
  correctly placed in the shared validator instead of special-cased in SWORD.
- **The `wiring.py` extraction** removes a genuine Flask coupling —
  `config_backend_api` could not previously be used from a non-Flask process.

---

## 1. Only `SwordFault` has an exception handler (High) — FIXED

`submit_ce/sword/app.py:179` registers a handler for `SwordFault` and nothing
else. Any other exception escapes to Starlette's default 500 handler, whose body
is plain text or HTML — unparseable by a SWORD client that expects
`sword:error`.

This is reachable, not theoretical. Two consecutive replacements of the same
paper:

```
replacement #1 -> 202
replacement #2 -> NoSuchSubmission: Submission 2 not found   (unhandled)
```

Decision 6 of the plan was "the same failure surface as legacy", but legacy's
CGI wrapped the entire request, so a Perl die still produced an error document.

**Fix:** add a catch-all handler that logs the traceback and renders `ENAVL` (or
a generic code) as a `sword:error`. Without it, the error-document work does not
hold at the boundary where it matters most.

**Fixed.** `_unexpected_error_handler` at `submit_ce/sword/app.py:184` renders
`ENAVL`/503 — 503 rather than a 500 code because the legacy set has none, this is
what legacy answered when it could not proceed internally
(`AtomPP.pm:258,501`), and it tells a batch depositor to retry rather than to
treat the deposit as permanently refused. No internal detail reaches the client.

Writing the tests found a bug in the first version of the handler: it used
`logger.exception()`, which logged `NoneType: None`. The handler is sync, so
Starlette runs it in a threadpool where `sys.exc_info()` is empty — every
traceback would have been discarded in production, making "the detail goes to the
log instead" a false promise. Now `exc_info=exc`, with a comment so nobody
simplifies it back.

Seven tests in `submit_ce/sword/tests/test_failure_surface.py`, including that a
planned `SwordFault` still reaches its own handler — an `Exception` handler is
easy to get wrong in the direction of catching everything, which would turn a 401
into a 503 and make clients retry instead of fixing credentials. Confirmed
non-vacuous: disabling the handler fails 4 of the 7.

## 2. `announced_submission_id()` ignores announced status (High) — FIXED

`submit_ce/sword/replace.py:111-121` selects the highest `submission_id` for a
`doc_paper_id` with **no status filter**, despite its name, and despite
`CreateSubmissionVersion.validate_pre_lock` requiring `is_announced`
(`submit_ce/domain/event/__init__.py:157`).

So a second PUT resolves to the unannounced v2 row created by the first, and
fails — this is the direct cause of finding 1's traceback.

Legacy had a concept for this condition: `submit_ce/sword/tracking.py:52`
already carries `CONFLICTING_SUBMISSION = "conflicting submission active"`. But
that value is only ever *read*, from a `failed - conflict` paper_id that the
legacy pipeline wrote. Nothing in the new PUT path *detects* the condition.

**Fix:** filter to announced submissions, and raise `EPSUB` when a version is
already in flight. Rename the function if it keeps the loose behaviour.

**Fixed.** `announced_submission_id` now filters
`status.in_(ANNOUNCED_STATUSES)`, and a new `pending_submission_id` finds a
non-announced, non-deleted row for the paper. The route checks it after ownership,
so only an owner learns the paper's state, and raises `EPSUB` — "submission
pending, not replaceable", the code legacy already used for pending targets:

```
#1 -> 202
#2 -> 400 code=4294967296 submission pending, not replaceable:
        '2607.00001' already has submission 2 in progress
```

Status values come from `LegacySubmissionRow.ANNOUNCED`/`.DELETED` rather than
inline `7`/`27`, because the `arxiv.db` mapper the sword code queries through
carries no status constants.

On parity: legacy detected this too, but only *after* accepting the deposit — the
processing fork wrote `'failed - conflict'` into `arXiv_tracking`
(`AtomPP.pm:1310-1313`) and the depositor discovered it by polling. submit-ce
deposits inside the request, so refusing up front is strictly better; the
reasoning is in the docstring so nobody "restores parity" later.

Nine tests in `test_replace.py`, including that a refusal creates no third
version, that a *deleted* version does not block a replacement, and that a
non-owner never sees `EPSUB`.

## 3. `/sword-license` POST has no CSRF token (High) — FIXED

`submit_ce/ui/templates/submit/sword_license.html:23` is a hand-written
`<form method="post">` with no token. There is **no global `CSRFProtect`** in
`submit_ce/ui/factory.py`, and every other POST form in the repo goes through
`arxiv.forms.csrf.CSRFForm`:

- `submit_ce/ui/controllers/new/classification.py:111` — `class ClassificationFormV2(csrf.CSRFForm)`
- `submit_ce/ui/templates/submit/classification.html:28` — `{{ form.csrf_token }}`
- `submit_ce/ui/templates/submit/file_upload.html:138` — same

**Impact:** a logged-in user visiting an attacker's page can have their default
SWORD license silently changed — including to `no`, which disables their
deposits, or to a license they did not choose, which then attaches to future
deposits as the legal record.

**Fix:** add a token. This revision's advice — "use `CSRFForm` like the rest of the
UI" — was given without reading the package, which turns out to document itself as
unusable; see finding 13 and the corrections below.

**Fixed** with `SwordLicenseForm(csrf.CSRFForm)` in
`submit_ce/ui/controllers/sword_license.py`, plus `{{ form.csrf_token }}` in the
template, validated before the license value is looked at. `CSRFForm` was chosen
over a session-bound alternative as an explicit call for consistency with the rest
of the app, with finding 13's caveat recorded in the class docstring.

`License` is deliberately **not** a form field: rendering it through a WTForms
widget would change the radio markup that
`arxiv-test-regression/pytest/tests/test_sword.py:43,51` matches exactly. The
template keeps its hand-written loop and the value is still checked against
`offered_licenses`.

After a successful POST the controller builds a **fresh** form — the submitted
token is spent, and echoing it back would leave the depositor unable to make a
second change.

Seven tests cover missing, forged, malformed and expired tokens. Each asserts the
stored license is **unchanged** rather than absent: the first version asserted
`is None` and failed under test ordering, because the `app` fixture outlives a
single test and an earlier test had already written a row. Confirmed non-vacuous:
disabling the check fails all four enforcement tests.

## 4. Wrapper deposits are not size-capped before parsing (Medium) — FIXED

`check_size` is called only from `save()` —
`submit_ce/sword/deposits.py:282` and `submit_ce/sword/gs_deposits.py:102` —
which is the **media** path only. The wrapper path goes straight to
`parse_document` → `etree.fromstring`.

Measured:

```
media   52,428,804 bytes -> 415
wrapper 52,428,887 bytes -> 400 (size-capped: no)
```

Both are rejected, so there is no crash — but the 50 MB document is fully parsed
into an lxml DOM first, roughly 3–5× the source in RAM. At `_CONCURRENCY: '8'`
that is a plausible OOM.

**This is a regression from legacy, not merely a gap.** `$CGI::POST_MAX`
(`AtomPP.pm:9`) was enforced by CGI.pm against `Content-Length` before the body
was read, for *any* POST regardless of content type — so it covered wrapper
deposits as well as media. submit-ce caps only the media path, so a wrapper is
now less constrained than it was under the Perl.

**Fix:** cap the payload before `parse_document`, so both paths share one limit
and one error.

**Fixed.** The check moved out of the store and into a free function,
`deposits.check_deposit_size`, called from every route that accepts a body — the
collection `POST` and the `PUT` replace path — before the checksum, so an oversize
body is not hashed first. `DepositStore.check_size` now delegates to it and stays
as the store-level invariant for anything reaching a store directly.

Six tests in `test_media_deposit.py` and one in `test_replace.py`, including that
both content types report the *same* code, that the limit is inclusive, and that
size is reported ahead of a bad checksum. Confirmed non-vacuous: removing the two
route calls fails 4 of them.

## 5. Oversize answers 415 with a self-contradicting document (Medium) — FIXED

`check_size` raises `EMDTP`, whose canonical text is *"media type specified is
not supported"* (`submit_ce/sword/errors.py:101`), while the summary reads
*"deposit of N bytes exceeds the M byte limit"*. The error document contradicts
itself.

~~Legacy never enforced the cap at all — `maxUploadSize` appears only in
`ServiceDoc.pm:120`, advertised and never checked — so this is new code and free
to choose 413.~~ **Wrong; corrected below.**

Legacy did enforce a cap, one layer above the SWORD code:

| Where | Value | Meaning |
|---|---|---|
| `AtomPP.pm:9` | `$CGI::POST_MAX = 10485760` | enforced, 10 MiB exactly |
| `ServiceDoc.pm:60` | `my $maxuploadsize = 10000` | advertised, 10,000 kB ≈ 9.77 MiB |

Two independent hardcoded numbers, with the advertised value ~245 KB *below* the
enforced one — accidentally the safe direction.

Nothing enforced it in Apache: `arxiv-httpd/conf/sword.conf` sets no
`LimitRequestBody`, and neither does anything else in `arxiv-httpd/`, so Apache's
default of unlimited applied. `cgi-bin/sword.pl` is a 16-line stub that only calls
`arXiv::AtomPP::AtomPP->new()->run()`. The limit was purely CGI.pm's.

The recommendation to use **413 gets stronger, not weaker**: CGI.pm's own overflow
message is literally `"413 Request entity too large"`. And legacy's failure
surface here was poor in a way worth not reproducing — `$CGI::cgi_error` is never
checked anywhere in `arXiv::AtomPP`, so an oversize deposit did not get a clean
413. CGI.pm stopped reading and left the parameters empty, and the request then
failed further down as though the body were malformed.

**Fixed** with a new code rather than by overloading an existing one:

```python
_ADDITIONS = [
    _e("ESIZE", 34359738368, "deposit exceeds the maximum upload size",
       E_CONTENT, 413),
]
```

Since legacy produced no errorcode for this condition at all, there is nothing to
be backward compatible with, and mapping it onto `EMDTP` would have been inventing
a *wrong* answer rather than a new correct one. `34359738368` is 2^35, continuing
the sequence so the OR-ing the code numbers are designed for keeps working, and
413 is the status CGI.pm itself named.

**This is a deliberate deviation from the 39-code table** and the only one in the
port. It is kept in a separate `_ADDITIONS` list so `_TABLE` remains a faithful
transcription, and `test_errors.py` now pins the legacy set at exactly 39 while
requiring any addition to be declared in a matching `ADDITIONS` dict — so a future
one cannot slip in unnoticed.

## 6. Advertised 50 MB may exceed the Cloud Run request limit (Medium)

The service document promises `maxUploadSize` 51200 kB
(`submit_ce/sword/atom/servicedoc.py`, per plan decision 5). Cloud Run caps
HTTP/1 request bodies below that.

### The size limits, all of them

Legacy had **three** different numbers, in three places, measuring different
things. Collected here because the branch's decision 5 only makes sense against
the third, and the review's first revision got this wrong by only finding the
second.

| Limit | Where | Value | Scope |
|---|---|---|---|
| `$CGI::POST_MAX` | `AtomPP.pm:9` | 10,485,760 B = 10 MiB | one HTTP POST — transport |
| `sword:maxUploadSize` | `ServiceDoc.pm:60` | 10,000 kB ≈ 9.77 MiB | advertised, per deposit |
| `MAXSIZE` / `MAXUNSIZE_TOTAL` / `MAXUNSIZE_PER` | `arXiv/Submit/Size_limits.pm:18-28` | 50,000 kB = **50 MB** each | the *submission*, all paths |

`Size_limits.pm` is the one that matters, and it is shared with the whole
submission system rather than SWORD-specific. All three keys hold only
`'default'` — no per-archive overrides are actually configured, despite the
per-archive API — and both getters honour `$ENV{OVERRIDE}` (doubles) and
`$ENV{MAXSIZE}` (raises), so ops could lift them without a deploy.

**So legacy's 10 MiB was a transport cap deliberately *below* the submission
limit.** A depositor wanting a 40 MB submission split it across several media
deposits and referenced them all from one wrapper — which is exactly what the
manual tells them to do:

> it may be useful to individually deposit large figures or other material of
> substantial file size, instead of attempting to upload everything at once
> — `submit_sword.md:317`

This makes decision 5 better-founded than the plan states: 50 MiB is not an
arbitrary 5× bump, it aligns SWORD's per-deposit cap with arXiv's actual
submission limit. submit-ce derives it from
`submit_ce.domain.size_limits.SIZE_LIMIT_POLICY.total_limit()` (52,428,800 B),
the same policy behind the UI's oversize warning, so the advertised and enforced
values cannot drift the way legacy's two hardcoded numbers could.

Two consequences worth carrying forward:

- **The two caps measure different things.** `MAXUNSIZE_TOTAL` is *uncompressed*.
  A 50 MiB zip that unpacks past the submission limit passes the SWORD cap and is
  flagged oversize downstream. They coincide numerically and not semantically.
- **A SWORD depositor gets no oversize signal.** `is_oversize` is a soft gate: the
  UI flashes a warning and the submission is auto-held at finalize
  (`ui/controllers/new/upload.py:272-287`). Nothing in `submit_ce/sword/` reads or
  reports it, so a depositor whose submission will be held learns that only by
  polling tracking. Not a regression — legacy's SWORD path did not surface it
  either — but the 50 MiB cap makes it far easier to reach.

The Cloud Run question stands on its own: whichever number is advertised, confirm
the platform will carry it.

**The published manual needs updating with this change.**
`arxiv-docs/source/help/submit_sword.md:224` shows
`<sword:maxUploadSize>10000</sword:maxUploadSize>` in its worked example, and
:237-238 describes the field as "the maximal allowed size of uploads in kB". A
depositor reading the manual will size their client against 10 MB and keep
splitting deposits they no longer need to split. That is a change in a different
repo and belongs on the release checklist, not in this branch.

**Verify before deploy.** If the platform limit is lower, a 40 MB deposit dies
at the edge with a platform 413 and no `sword:error` body — precisely the opaque
failure this branch otherwise works hard to avoid. Either lower the advertised
value or confirm the deployment can accept it.

## 7. `/docs`, `/redoc`, `/openapi.json` served publicly (Medium) — FIXED

Confirmed by request against the app: all three return 200 without credentials.
Legacy exposed nothing under the SWORD app unauthenticated — `sword.conf` gated
`/sword-app` at the Apache layer.

The only mitigation is edge routing that **does not exist yet**, and
`cicd/cloudbuild-sword-dev-arxiv.yaml` sets no `--ingress`.

**Fix:** `docs_url=None, redoc_url=None` in `create_sword_app`, and consider
`--ingress=internal-and-cloud-load-balancing`.

**Fixed in two layers.**

*In the app*, `create_sword_app` passes all three URLs as `None` unless
`settings.LOCAL_LOGIN` is set, which removes the routes outright — a **404**, not a
401 that would still advertise a schema exists. `openapi_url` is the important one
of the three: dropping only the HTML pages would leave the machine-readable schema
served.

Measured route tables:

```
LOCAL_LOGIN=<unset>    docs=NONE                                total_routes=9
LOCAL_LOGIN=1          docs=[/docs, /redoc, /openapi.json, ...] total_routes=13
```

`LOCAL_LOGIN` was reused rather than adding a setting: it is already the repo's
"developer on a laptop" switch and it admits fake sessions, which is strictly more
dangerous than a schema page. On this app it has no other effect — its only other
consumers are the Flask UI's `/debug/login` routes (`ui/factory.py:56`,
`ui/routes/ui.py:634,652`), and the SWORD app has no such route. The tradeoff is
that docs cannot be enabled on a deployed instance without also enabling fake
logins; that is the safe direction, and a dedicated flag can be added if it is
ever wanted.

`local_sword.py` now sets `LOCAL_LOGIN=1` — `local_ui.py` already did, and without
it the gate would have denied docs on a laptop too, which was the whole point of
keeping them.

*In the deploy*, `cicd/cloudbuild-sword-dev-arxiv.yaml` now passes
`--ingress=$_INGRESS`, defaulting to `internal-and-cloud-load-balancing`, so the
service's own `*.run.app` URL is not reachable from the internet at all. This is
the layer that holds if the app is ever misconfigured, and it covers every endpoint
rather than just the docs pages. The substitution exists so it can be set to `all`
temporarily while load-balancer routing for `/sword-app/*` and `/resolve/app/*` is
being set up.

Six tests in `test_app_wiring.py`: all four doc paths 404 by default, the schema
route absent from the route table *and* `app.openapi_url is None`, the pages
present under `LOCAL_LOGIN`, and — the one that matters most — that the protocol
routes and `/status` are untouched by the flag. Confirmed non-vacuous: removing the
three kwargs fails 2 of them.

## 8. GCS id counter is a single-object write hotspot (Medium) — ACCEPTED

Every `allocate_id()` performs a read plus a conditional write against one
object (`submit_ce/sword/gs_deposits.py:74-95`).

The CAS logic itself is **correct** — the interleaving was traced: two writers
reading generation G both attempt `if_generation_match=G`, one wins, the loser
gets 412, retries, reads the new value, and writes one more. No lost updates.

The concern is throughput, not correctness: GCS advises against sustained writes
above roughly 1/sec to a single object, and each retry is a full round trip.
Fine for a handful of automated depositors.

**Accepted** (2026-08-11): SWORD has on the order of five depositors, all
automated clients submitting in modest batches. One read plus one conditional
write per deposit is nowhere near GCS's ~1 write/sec-per-object guidance, so the
ceiling is real but unreachable at this scale.

Recorded rather than closed, because the acceptance rests on the user count rather
than on the design:

- **If the depositor population grows substantially**, or a bulk backfill ever
  drives deposits concurrently, revisit. The symptom would be ENAVL 503s from
  `allocate_id` exhausting `MAX_ALLOCATION_ATTEMPTS`, not corruption.
- **Correctness does not depend on this decision.** The CAS was traced and holds
  under contention; the accepted item is throughput alone. A future reader hitting
  503s here should reach for a DB sequence, not suspect lost updates.

No code change.

## 9. The socket test guard does not stop gRPC (Low)

The root `conftest.py` docstring claims the guard "turns 'no test happens to
reach out' into 'no test can'". Tested:

```
python socket -> BLOCKED
grpc          -> TIMED OUT - it dialled; the guard never raised
```

gRPC's C core bypasses Python's `socket` module, so the exact transport that
motivated the guard — a Pub/Sub call over gRPC — is the one it does not cover.

Practically contained by layer 1 (`QA_PUBSUB_ENABLED=False`, which does stop the
publisher), but the docstring overstates, and any future gRPC client (Cloud SQL
connector, Firestore, GCS over gRPC) would slip through.

**Fix:** correct the docstring to scope the claim to Python-socket traffic.

## 10. Nits

Individually minor; grouped so none is lost.

**Docstrings that overstate or misdescribe:**

- `submit_ce/sword/auth.py:75-77` — "the three are deliberately
  indistinguishable" is true of the response body but false of timing: an
  unknown nickname skips bcrypt entirely. Drop the claim or hash a dummy.
- `submit_ce/sword/auth.py:130-135` — says "any account with that address
  counts" but uses `.first()`. The Perl also reads a single row
  (`AtomPP.pm:_is_email_bad`), so the *behaviour* is faithful; only the comment
  is wrong.

**Robustness:**

- `submit_ce/sword/collections.py:135-141` — `.first()` with no `ORDER BY`, then
  a Python case re-check. Correct, and it does neutralize MySQL's
  case-insensitive collation, but non-deterministic if a case-variant nickname
  pair ever exists — which would present as flaky authentication. An
  exact/binary-collation filter would be firmer.
- `submit_ce/sword/atom/parse.py:151` — the lxml parser is unconfigured. Probed:
  external entities are not resolved and libxml2 caps entity amplification, so
  there is **no live XXE or billion-laughs vulnerability**. But that safety
  rests entirely on library defaults. `XMLParser(resolve_entities=False,
  load_dtd=False, no_network=True)` plus a regression test would pin it.
- ~~`submit_ce/ui/controllers/sword_license.py:84` — raises `BadRequest` for an
  anonymous visitor instead of redirecting to login.~~ **Withdrawn**, see
  [Corrections](#corrections-to-the-first-revision): an anonymous request is a 401
  from upstream and never reaches the controller.

**Compatibility notes (no data exposed, but record the decision):**

- Unauthenticated catch-all routes answer 400/501 where legacy's Apache would
  have challenged with 401.
- `/resolve/app/{id}` is unauthenticated, matching legacy (`sword.conf` did not
  gate `/resolve`). But deposit ids are sequential and the response can carry
  `autotex_log_b64`, making submission ids, statuses, and LaTeX logs
  enumerable. Previously raised and declined — recorded here so it stays a
  decision rather than becoming an oversight.

**Tests:**

- `submit_ce/sword/tests/test_tracking.py:175` accepts three statuses
  (`"submitted", "incomplete", "on hold"`) when the outcome is deterministic —
  nothing triggers compile, so it is always `incomplete`. Would pass through a
  silent behaviour change.
- `submit_ce/sword/tests/test_media_deposit.py:196` disjuncts over XML escaping
  (`&#39;` or `'`). Assert the encoding actually produced.

**Housekeeping:**

- `submit_ce/ui/tests/test_backend_email_service.py` still lives under
  `ui/tests/` though the code moved to `submit_ce/implementations/wiring.py`.
- `PaperOwner.valid` and `flag_author` are ignored by
  `submit_ce/sword/replace.py:91-97`. **This is faithful** — legacy's subquery
  ignores them too. Worth a separate ticket against the legacy behaviour, not a
  change on this branch.

---

## 11. A replacement's new row has no events, so it cannot be loaded (High)

Found while testing finding 2's fix, and more serious than the finding that
exposed it.

A replacement creates a new `arXiv_submissions` row, but **every event stays under
the original submission's id**. Measured after one replacement:

```
submission_id=1 version=1 type=new status=7 events=17
submission_id=2 version=2 type=rep status=0 events=0
```

The cause is `_new_dbevent` at
`submit_ce/implementations/legacy_implementation/db.py:650`, which stamps each row
with `event.submission_id` — for `CreateSubmissionVersion` that is the submission
being *versioned*, not the one being created. So `get_events()` on the new row
raises `NoSuchSubmission`, and a paper cannot be replaced a second time even after
the intermediate version is announced.

**Pre-existing and shared.** This is the legacy implementation's persistence, so
the Flask UI's replacement flow versions an already-replaced paper no better than
SWORD does. Verified by inspecting the event rows directly; the UI flow was not
driven.

Pinned as `@pytest.mark.xfail(strict=True, raises=NoSuchSubmission)` on
`test_a_replacement_is_allowed_again_once_the_version_is_announced` in
`test_replace.py`, with the diagnosis in the reason. It asserts the behaviour we
want and will fail loudly when someone fixes it.

**Not fixed here** — it is outside SWORD, affects the UI equally, and deserves its
own change with its own verification.

## 12. A malformed CSRF token is a 500 (Medium)

`SessionCSRF._split` in `arxiv.forms.csrf` does `csrf_token.split('::', 1)` and
unpacks two values unconditionally, so a token with no `::` raises `ValueError`
out of `form.validate()`. WTForms catches `ValidationError`, not `ValueError`, so
the request becomes a 500 — from input any client can send.

**Worked around** in `sword_license` by catching `ValueError` around `validate()`
and treating it as invalid, with a comment naming the cause. The bug itself is in
`arxiv-base` and wants a ticket there.

## 13. `arxiv.forms.csrf` is documented "DO NOT USE" (accepted)

The package's own module docstring:

> DO NOT USE THIS PACKAGE. This package is flawed and not currently used in
> production. It assumes the client will respond on the same IP address that it
> used to request the form. Look at the wtforms CSRF docs and use the examples
> there.

It also emits a `DeprecationWarning`. The practical consequence is that a
depositor whose address changes between loading `/sword-license` and submitting it
gets a spurious failure — plausible on mobile or behind a proxy pool.

**Accepted deliberately.** Every other form in submit-ce uses it
(`controllers/new/classification.py:111`), `wtforms` 3.1.2 is already a
dependency and `flask-wtf` is not, and `CSRF_SECRET` is already configured for it.
Consistency won over correctness here on the grounds that the alternative leaves
the app with two CSRF mechanisms. Migrating all forms to a session-bound token is
its own change, and is the real fix.

---

## Corrections to the first revision

Two claims in this document were wrong. Recorded rather than quietly edited, since
the first revision may have been read already.

- **"Use `CSRFForm` like the rest of the UI. This is a straightforward convention
  break, not a design tradeoff."** Wrong on the second half. The recommendation
  was made without reading the package, which documents itself as unusable
  (finding 13). It *is* a design tradeoff, and the choice was escalated rather
  than assumed.
- **"`sword_license.py:84` raises `BadRequest` for an anonymous visitor instead of
  redirecting to login"** (in the nits). Wrong: an anonymous request never reaches
  the controller — `test_post_requires_authentication` and
  `test_page_requires_authentication` both assert **401**, produced upstream. The
  `BadRequest` guard covers a session that exists without a user, which is not the
  anonymous case. That nit is withdrawn.
- **"Legacy never enforced the cap at all"** (finding 5). Wrong twice over.
  `AtomPP.pm:9` sets `$CGI::POST_MAX = 10485760`, a hard 10 MiB enforced by
  CGI.pm; and `arXiv/Submit/Size_limits.pm` carries a 50,000 kB submission limit
  shared by every submission path. The original search covered `AtomPP.pm` and
  `ServiceDoc.pm` for `maxUploadSize|MAX_UPLOAD|too large|ErrorContent|413`, which
  `$CGI::POST_MAX` and `MAXUNSIZE_TOTAL` both fail to match — "grep found nothing"
  is not "nothing is there", especially across a multi-repo workspace where the
  governing limit lived in neither file being read.

  Worse: `submit_ce/sword/atom/servicedoc.py:78-80`, **in the branch under
  review**, already documents `CGI::POST_MAX` and the 240 kB under-advertisement.
  The correct value was in the diff the whole time, and the review contradicted
  its own source. Reading the code being reviewed is not optional when the claim
  is about what that code says.

  Corrected in findings 4, 5 and 6. Every conclusion gets sharper: finding 4 turns
  out to be a regression rather than a gap, 413 is more clearly right than 415, and
  decision 5 turns out to be well-founded rather than arbitrary.

---

## Investigated and found to be non-issues

Recorded so they are not re-raised. Each of these looked like a defect and was
not:

- **Nickname case-sensitivity vs MySQL collation.** `nickname_to_user_id`
  re-checks the match in Python (`collections.py:139`), so case-sensitivity
  holds regardless of column collation.
- **Client-supplied username recorded as the deposit owner**
  (`auth.py:160`). Safe, because the Python re-check above guarantees the
  supplied string equals the stored nickname exactly.
- **XXE and entity expansion.** Both refused — external entities are not
  resolved, and libxml2 raises *"Maximum entity amplification factor
  exceeded"*. See nit above for the defence-in-depth suggestion.
- **`_find_media_blob` prefix collisions.** The prefix ends in `.`
  (`gs_deposits.py:118`), so `26080001.` cannot match a longer id.
- **CAS correctness under contention.** Traced; no lost updates. See finding 8.
- **Domain validators bypassing SWORD's ladder.** Probed `physics.gen-ph`,
  general-primary-with-secondary, and over-limit secondaries — all return 400
  with a `sword:error`, caught by SWORD's own validation before the domain
  layer sees them.
- **`STORE` fallback to the in-memory deposit store.** Already fixed at
  `a680dfb`: `build_deposit_store` is now exhaustive and raises
  `NotImplementedError` on an unrecognized value.

## Coverage observation

The gap is not line coverage but **state-dependent paths**. The
double-replacement bug (findings 1 and 2) sat behind 100% statement and branch
coverage because no test drove two replacements in sequence.

Worth adding cases that exercise repeated and interleaved operations rather than
one-shot flows.

Fixing 1–3 bore this out. Every defect found in that work — the discarded
tracebacks, the un-loadable replacement row (finding 11), the 500 on a malformed
token (finding 12) — came from a *test written against the fix*, not from reading
the code. Two of the three fix-verifying tests were themselves wrong on the first
attempt (`is None` under a shared fixture; asserting an unhandled error on a path
that had just become a planned refusal). Coverage was 100% throughout.

## Outstanding from the plan

Not review findings — restated for completeness:

- **Nothing triggers compilation**, so `SetSourceFormat` and
  `FinalizeSubmission` never fire, and tracking reports `incomplete` where
  legacy reported `submitted`.
- **Step 15's acceptance gate** against a deployed dev instance is still open;
  `_TRIGGER_ID` is empty in `cicd/cloudbuild-sword-dev-arxiv.yaml`, and edge
  routing for `/sword-app/*` and `/resolve/app/*` is not in place.

## Recommendation

Findings 1–3 are done: 1 and 2 were correctness, 3 was security, and all three
were blockers on the service being reachable by clients.

Findings 4, 5 and 7 are done too — one size limit across every path that takes a
body, reported as 413 under its own errorcode, and the interactive docs restricted
to local runs with Cloud Run ingress narrowed behind them.

What now gates a deploy, in order:

1. **Finding 11** — a paper cannot be replaced twice. Outside SWORD and affecting
   the UI equally, so it needs its own change, but it is a functional hole in the
   replacement feature this branch ships.
2. **Finding 6** — confirm the platform accepts the advertised 50 MB.
3. **The manual** (`arxiv-docs`) still advertises 10000 kB. Depositors read it.
4. **Edge routing** for `/sword-app/*` and `/resolve/app/*`, which the new
   `--ingress` default now depends on: with it set, the service is unreachable
   until the load balancer is pointed at it.

Finding 8 is accepted at the current scale of ~5 automated depositors. Findings 9,
10, 12 and 13 can follow at leisure; 12 and 13 are tickets against `arxiv-base`
rather than work in this repo.

Verification at the time of this revision: `submit_ce/sword` **635 passed, 1
xfailed** at 100% statement and branch; full `./test.sh` **1226 passed, 57
skipped, 1 xfailed**; `./lint.sh` clean.
