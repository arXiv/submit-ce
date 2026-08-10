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
| 4 | Medium | Wrapper deposits are not size-capped before parsing | `sword/deposits.py` | Open |
| 5 | Medium | Oversize deposits answer 415 with a self-contradicting error document | `sword/errors.py` | Open |
| 6 | Medium | Advertised 50 MB `maxUploadSize` may exceed the Cloud Run request limit | `cicd/` | Open |
| 7 | Medium | `/docs`, `/redoc`, `/openapi.json` served publicly | `sword/app.py` | Open |
| 8 | Medium | GCS id counter is a single-object write hotspot | `sword/gs_deposits.py` | Open |
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

## 4. Wrapper deposits are not size-capped before parsing (Medium)

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

**Fix:** cap the payload before `parse_document`, so both paths share one limit
and one error.

## 5. Oversize answers 415 with a self-contradicting document (Medium)

`check_size` raises `EMDTP`, whose canonical text is *"media type specified is
not supported"* (`submit_ce/sword/errors.py:101`), while the summary reads
*"deposit of N bytes exceeds the M byte limit"*. The error document contradicts
itself.

Legacy never enforced the cap at all — `maxUploadSize` appears only in
`ServiceDoc.pm:120`, advertised and never checked — so this is new code and free
to choose 413, which is what HTTP means by it.

## 6. Advertised 50 MB may exceed the Cloud Run request limit (Medium)

The service document promises `maxUploadSize` 51200 kB
(`submit_ce/sword/atom/servicedoc.py`, per plan decision 5). Cloud Run caps
HTTP/1 request bodies below that.

**Verify before deploy.** If the platform limit is lower, a 40 MB deposit dies
at the edge with a platform 413 and no `sword:error` body — precisely the opaque
failure this branch otherwise works hard to avoid. Either lower the advertised
value or confirm the deployment can accept it.

## 7. `/docs`, `/redoc`, `/openapi.json` served publicly (Medium)

Confirmed by request against the app: all three return 200 without credentials.
Legacy exposed nothing under the SWORD app unauthenticated — `sword.conf` gated
`/sword-app` at the Apache layer.

The only mitigation is edge routing that **does not exist yet**, and
`cicd/cloudbuild-sword-dev-arxiv.yaml` sets no `--ingress`.

**Fix:** `docs_url=None, redoc_url=None` in `create_sword_app`, and consider
`--ingress=internal-and-cloud-load-balancing`.

## 8. GCS id counter is a single-object write hotspot (Medium)

Every `allocate_id()` performs a read plus a conditional write against one
object (`submit_ce/sword/gs_deposits.py:74-95`).

The CAS logic itself is **correct** — the interleaving was traced: two writers
reading generation G both attempt `if_generation_match=G`, one wins, the loser
gets 412, retries, reads the new value, and writes one more. No lost updates.

The concern is throughput, not correctness: GCS advises against sustained writes
above roughly 1/sec to a single object, and each retry is a full round trip.
Fine for a handful of automated depositors.

**Action:** document as the known ceiling, or move the counter to a DB sequence
if deposit volume grows.

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

What now gates a deploy, in order:

1. **Finding 11** — a paper cannot be replaced twice. Outside SWORD and affecting
   the UI equally, so it needs its own change, but it is a functional hole in the
   replacement feature this branch ships.
2. **Findings 6 and 7** — both are deployment-shaped and cheap: confirm the
   platform accepts the advertised 50 MB, and stop serving `/docs` publicly.
3. **Finding 4** — cap the wrapper payload before parsing.

Findings 5, 9, 10, 12 and 13 can follow at leisure. 12 and 13 are tickets against
`arxiv-base` rather than work in this repo.

Verification at the time of this revision: `submit_ce/sword` **621 passed, 1
xfailed** at 100% statement and branch; full `./test.sh` **1212 passed, 57
skipped, 1 xfailed**; `./lint.sh` clean.
