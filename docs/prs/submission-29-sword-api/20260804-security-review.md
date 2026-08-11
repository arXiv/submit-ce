# Security review — `SUBMISSION-29-sword`

- **Date:** 2026-08-04
- **Branch:** `SUBMISSION-29-sword` @ `a680dfb` vs `origin/develop`
- **Scope:** the 78 files changed by this branch — the new SWORD v2 deposit API
  (`submit_ce/sword/**`), the new `/sword-license` UI controller and template, wiring/DB
  changes, `Dockerfile`, and [`cicd/cloudbuild-sword-dev-arxiv.yaml`](https://github.com/arXiv/submit-ce/tree/develop/cicd/cloudbuild-sword-dev-arxiv.yaml). Security implications
  **newly introduced by this branch** only; pre-existing issues are out of scope.
- **Method:** full-diff read plus source inspection of the surrounding modules; every
  candidate finding was then independently adversarially verified against the code.

## Result

**No confirmed vulnerabilities.** Two candidates were raised and both were refuted on
verification. Nothing on this branch blocks merge on security grounds.

The sections below record what was examined so the next reviewer does not have to redo it.

---

## Candidates raised and refuted

### 1. Unauthenticated `GET /resolve/app/{sword_id}` — REFUTED (inherited public behavior)

`resolve` ([`submit_ce/sword/app.py:499`](https://github.com/arXiv/submit-ce/tree/develop/submit_ce/sword/app.py#L499)) is the only route in the new SWORD app that takes
no credentials and applies no ownership check. Every sibling route takes
`credentials: HTTPBasicCredentials = Depends(_basic)` and calls
`sword_auth.depositor_from_credentials` plus `store.owned_by` / `require_owner`. The lookup
is keyed on the caller-supplied integer alone (`tracking.py:129` —
`filter_by(sword_id=sword_id).one_or_none()`), deposit ids are sequential (`YYMM` + a global
4-digit counter, `deposits.py:113`), and the response really does carry
`autotex_log_b64` (`tracking.py:150`). All mechanically true, and there is a test asserting
it (`tests/test_tracking.py:66`, `test_no_authentication_required`).

Refuted on scope and sensitivity:

- **Not new exposure.** This is a field-for-field port of
  [`arxiv-submit/lib/arXiv/Controller/Sword.pm:21-99`](https://github.com/arXiv/arxiv-submit/tree/develop/lib/arXiv/Controller/Sword.pm#L21-L99), which is live in production at the
  same public path, equally unauthenticated, and base64-attaches the same compile log
  (`Sword.pm:39-52`). [`docs/sword-getting-started.md:144`](../../sword-getting-started.md#L144) demonstrates the "exploit"
  working against prod today. The branch moves the route; it does not widen it.
- **It is a published client contract**, documented as a plain unauthenticated GET, and the
  decision is recorded three times with its consequence stated explicitly
  (`tracking.py:7-10`, `app.py:501-506`, `docs/plans/20260730-submission-29-sword-fastapi.md:1019`).
- **The log is build noise, not paper content.** A real `gcp_compile.log` is pdflatex
  machinery — counter allocations, TeX Live package versions, texlive paths, processed
  source filenames. No title, abstract, author names, or email addresses.
- `arxiv_id` is disclosed only for already-announced (public) papers (`tracking.py:157-161`),
  and `submission_errors` from `arXiv_tracking` is **not** emitted at all — the `error` field
  only ever carries one of four fixed constants (`tracking.py:49-53`).

Net disclosure to an anonymous enumerator: that deposit N exists, its workflow stage, its
internal `submission_id`, and which LaTeX packages it loads.

**Not a defect on this branch.** Closing it would be an API-breaking product decision for
the SWORD owner. If arXiv wants that: drop `autotex_log_b64` from `resolve_deposit`
(`tracking.py:150`) or gate it behind `depositor_from_credentials` + `store.owned_by`, and
replace the sequential deposit id with an unguessable tracking token. Worth noting that the
same artifact *is* owner-gated everywhere else in this codebase — the Flask UI serves it
only through an authenticated, ownership-checked controller
([`submit_ce/ui/controllers/new/process.py:271`](https://github.com/arXiv/submit-ce/tree/develop/submit_ce/ui/controllers/new/process.py#L271)).

### 2. Missing CSRF token on `POST /sword-license` — REFUTED (SameSite=Lax; defense-in-depth)

`sword_license.py:80-95` writes `arXiv_sword_licenses` for the session user straight from
`params.get("License")` with no form object and no token, and
`templates/submit/sword_license.html:23` renders the form with no `csrf_token` input. This
does deviate from the sibling controllers, which wrap params in `arxiv.forms.csrf.CSRFForm`
(`manage_submissions.py:19,33`; `withdraw.py:30`). There is no app-wide CSRF middleware —
`ui/factory.py` calls only `Base(app)`.

Refuted:

- The only browser-attached credential this app accepts is `ARXIVNG_SESSION_ID`
  ([`submit_ce/ui/auth.py:49-54`](https://github.com/arXiv/submit-ce/tree/develop/submit_ce/ui/auth.py#L49-L54)), and that cookie is issued `samesite='lax'`
  ([`arxiv-auth/accounts/accounts/routes/ui.py:78`](https://github.com/arXiv/arxiv-auth/tree/develop/accounts/accounts/routes/ui.py#L78)), guarded by `AUTH_SESSION_COOKIE_SECURE`
  which defaults to true. A cross-site form POST carries no cookie, so `before_request`
  raises `Unauthorized("no token or cookie")` (`ui/auth.py:226`) before the controller runs.
  The described attack never reaches the write.
- The residual same-site path needs an HTML-injection primitive that does not exist anywhere
  identified in this codebase — and an attacker holding one could read a CSRF token from a
  GET anyway, so the missing token would not have stopped it. Defense-in-depth, not a
  concrete vulnerability.
- Impact is lower than it first appears: the value is allowlist-constrained to arXiv's own
  offered license URIs plus the literal `"no"` (`sword_license.py:89-94`); the current
  setting is visible as `checked` on every GET (`sword_license.html:25`); and the worst-case
  value `"no"` makes deposits *fail loudly* with 412 ENLIC (`sword/auth.py:116-126`) rather
  than silently re-licensing anything.

One caveat on the "match the sibling pattern" framing: [`arxiv-base/arxiv/forms/csrf.py:1-10`](https://github.com/arXiv/arxiv-base/tree/develop/arxiv/forms/csrf.py#L1-L10)
opens with "DO NOT USE THIS PACKAGE. This package is flawed and not currently used in
production," and emits a `DeprecationWarning`. Adding CSRFForm here would adopt a module
arxiv-base tells callers not to use. Track CSRF for this app as its own decision.

---

## Verified non-issues

Checked and cleared, so they need not be re-audited:

- **XXE in [`submit_ce/sword/atom/parse.py:151`](https://github.com/arXiv/submit-ce/tree/develop/submit_ce/sword/atom/parse.py#L151)** (`etree.fromstring(document)`, default
  parser). Verified against the pinned `lxml==6.1.1` / libxml2 2.14.6 in this repo's venv:
  external general entities are refused (`Entity 'x' not defined`), the
  parameter-entity → general-entity exfiltration chain is refused (`PEReferences forbidden
  in internal subset`), and network entities are refused (`Attempt to load network entity`).
  A top-level `%pe;` in the internal subset does *open* a local file, but only the filename
  reaches the error message — no content exfiltration; residual risk is a file-existence
  oracle via the echoed parse error, too low-impact to flag.
  **This safety is incidental to the pinned version, not intentional** — [`pyproject.toml`](https://github.com/arXiv/submit-ce/tree/develop/pyproject.toml)
  pins only `lxml>=6.1.1`. Passing an explicit
  `etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)` would make it
  deliberate and version-independent. Recommended as hardening, not as a fix.
- **Path traversal / zip-slip via deposit ids:** `deposits.yymm_of` gates every GCS object
  path behind `^(\d{4})\d{4,}$`, so `_media_path` / `_entry_path` / `_shard` cannot be
  steered outside the prefix.
- **Response-header injection via `Content-Disposition`** (`app.py:319`):
  `request.parse_disposition_filename` restricts the echoed value to `[^;\s]+` then
  printable ASCII — no CR/LF.
- **Ownership on the deposit / edit / replace paths is enforced:** `store.owned_by` on both
  GET forms, `sword_replace.require_owner` on PUT, and `parse.py:363` closes the legacy
  `## FIXME: this should be fatal` hole that let a depositor attach another user's staged
  media. `GET /sword-app/edit/{id}` (the `edit-media` IRI) returns EBLOG rather than serving
  bytes, so there is no unprotected media-retrieval route.
- **Host-header trust** (`app.py:118-150`): `X-Forwarded-Host` / `-Proto` are unvalidated but
  only reflected into the requester's own response (Location, self-links); nothing is
  persisted or shared-cached.
- **No injection sinks in new code:** no raw SQL, `subprocess`, `eval`, `pickle`, or YAML
  deserialization. `collections.nickname_to_user_id` uses a parameterized `select()`, and
  `collections.demographic_flag`'s `getattr` is fed only from the `known_groups()` allowlist.

## Observations outside this review's scope

Noted in passing, pre-existing, not findings against this branch:

- [`submit_ce/ui/config.py:71`](https://github.com/arXiv/submit-ce/tree/develop/submit_ce/ui/config.py#L71) ships `CSRF_SECRET: str = "foobar"` as its default.
- [`submit_ce/ui/routes/ui.py:640`](https://github.com/arXiv/submit-ce/tree/develop/submit_ce/ui/routes/ui.py#L640) sets `ARXIVNG_SESSION_ID` without `samesite`/`secure`, but
  it is inside `/debug/login`, gated on `settings.LOCAL_LOGIN` with `raise NotFound()`
  otherwise — dev-only.

## Scope caveat

Reviewed the committed branch diff (`origin/develop...HEAD`). The working tree also holds
uncommitted edits to [`local_sword.py`](https://github.com/arXiv/submit-ce/tree/develop/local_sword.py) and [`local_ui.py`](https://github.com/arXiv/submit-ce/tree/develop/local_ui.py) and an untracked [`hack.py`](https://github.com/arXiv/submit-ce/tree/develop/hack.py), which
were **not** reviewed. [`hack.py`](https://github.com/arXiv/submit-ce/tree/develop/hack.py) should not be committed.
