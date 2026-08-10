# Design system review: `/sword-license` (SWORD default-license page)

**Context:** public · rendered page + source
**Reviewed against:** design-system @ `/Users/bgm37/Documents/arxiv/src/design-system`
(`docs/DESIGN-POLICIES.md`, `docs/BRAND.md`, `docs/color-mapping.md`, `docs/typography.md`,
`docs/public/header-styles.html`, `docs/public/footer-styles.html`,
`docs/public/button-styles.html`, `docs/public/link-styles.html`,
`docs/internal/form-styles.html`)

**Surface determination:** public. `/sword-license` is author-facing — a depositor sets their own
default license. DESIGN-POLICIES → *Internal vs. Public pages*: "Public pages: Everything a reader
or author sees on arxiv.org … use Open Blue as the primary action." Access Lime must not appear
here. The page correctly uses no lime today.

**Note on the rendered check:** the page returns 401 without a session cookie, so it was reviewed
from the HTML the Flask app actually produces (rendered through the test client's authorized
session) plus the CSS that HTML loads, not from a browser screenshot. Runtime behaviours that
depend on real viewport and input — hover/focus ring appearance, reflow at 320px, the header's
JS-dependent collapse — were reasoned about from the stylesheets rather than observed.

## Summary

The template change is the right move and is forward-compatible: it inherits the shared chrome via
`{% extends "base/base.html" %}` instead of hand-building it, which is exactly what the design
system asks for. Two things block compliance. First, the radio group has no `<label>` elements at
all — a hard accessibility violation that this template owns and can fix without touching the
strings the regression suites match. Second, the chrome the page now inherits is the *pre-spinout*
header and footer (Cornell logo, acknowledgment in the header), because submit-ce pins arxiv-base to
a feature branch that predates the approved `.ds-site-header` / `.ds-site-footer` chrome already on
arxiv-base master. Everything else is token and component drift shared with the rest of submit-ce.

## Blocking — accessibility & policy violations

### 1. Radio inputs have no `<label>` — owner: this template

`submit-ce/submit_ce/ui/templates/submit/sword_license.html:24`. Each option is a bare `<input
type="radio">` followed by a text node, closed with an invalid `</input>`. There is no `<label>`
anywhere on the page (verified: zero `<label` in the rendered output).

DESIGN-POLICIES → *Accessibility*: "**Labels:** Every form input must have an associated `<label>`
(visible or `sr-only`). Use `aria-label` when a visible label is impractical."

Why it matters: with no label association, a screen reader announces seven unnamed radio buttons —
the license name is adjacent text, not the control's accessible name — and clicking the license text
does not select its radio. This is the single most consequential finding on the page, and it is also
the one entirely within this PR's control.

**Fix.** Wrap each option in a `<label>`, replacing `</input>` with `</label>`:

```jinja
<label><input type="radio" name="License" value="{{ license.uri }}"{% if license.uri == selected %} checked="checked"{% endif %}>{{ license.label }}</label><br />
```

This is safe against both suites, verified rather than assumed:

- `arxiv-test-regression/pytest/tests/test_sword.py:33-52` asserts only the two exact
  `<input type="radio" name="License" value="…" checked="checked">` substrings and the sentence
  "then SWORD deposits will be accepted". It does **not** match `</input>`.
- `submit-ce/submit_ce/ui/tests/test_sword_license.py:18-21` builds the same substring, and
  `test_only_one_radio_is_checked` (line 115) counts `checked="checked"` occurrences — the wrapper
  changes neither.

The template's own comment (lines 11-16) says `</input>` is kept "for byte-compatibility with any
client scraping this page." Nothing in either suite depends on it, so that reason does not outweigh
the labels. If a scraper genuinely does, `<label>` can be added without removing `</input>` — invalid
either way, but no worse than today.

There is an in-repo precedent to match: `submit-ce/submit_ce/ui/templates/submit/license.html:140-146`
already wraps its license radios in `<label class="radio">`. `/sword-license` is the outlier.

### 2. Page renders the pre-spinout chrome, not the approved chrome — owner: the arxiv-base pin

The header this page now inherits carries the Cornell University logo and the sponsor acknowledgment
line ("We gratefully acknowledge support from the Simons Foundation, Schmidt Sciences, member
institutions…") *inside* `<header>`. Two policies:

- DESIGN-POLICIES → *Public pages*: "**Header:** Single bar. Black (phase 1, spinout) transitioning
  to Repository Brown (phase 2). Logo, Search, Submit, Donate, Log in. **No Cornell branding
  post-spinout.**"
- Same section: "All acknowledgements are presented in the footer, **never in the header**."

`docs/public/header-styles.html` further scopes the approved unit to "announcement band + black bar
(`.ds-announcement` / `.ds-site-header`) … which covers **ONLY** these two pieces; nothing below the
black bar is approved chrome."

**Root cause, and it is not this template.** `submit-ce/uv.lock:30` pins arxiv-base to
`?branch=SUBMISSION-80-LicenseDataUpdate#4f574284a39a1de5f88fefd6d2ec687e08a65f86`
(`submit-ce/pyproject.toml:117`). arxiv-base **master** (`b14b99f`, `1.0.1-849-gb14b99f`) already
ships the compliant chrome:

- `arxiv-base/arxiv/base/templates/base/header.html` is `<header class="ds-site-header">` — arXiv
  logo (`arxiv-logo-primary-light.svg`, no Cornell), nav of Search / Submit / Donate / Log in, a
  search overlay, and a hamburger wired only when JS enables it.
- `arxiv-base/arxiv/base/templates/base/footer.html` is `<footer class="ds-site-footer">` with the
  acknowledgment where it belongs, `<nav aria-label="Site navigation">`, and `aria-hidden="true"` on
  the dot separators — matching the `docs/public/footer-styles.html` behavior contract line for line.
- `arxiv-base/arxiv/base/templates/base/base.html` adds the spinout announcement band and loads
  `css/arxiv-header-footer.css`.

**Fix.** Move the arxiv-base pin to master. This page needs no template change — `{% extends
"base/base.html" %}` picks the new chrome up automatically, which is the main argument for the
approach this PR took.

The obvious objection — that the branch exists to carry license data this very page depends on — does
not hold: `arxiv-base/arxiv/license/__init__.py` is **byte-identical** to the pinned copy in
`submit-ce/.venv` (`diff -q` reports no difference), so the `CURRENT_LICENSES` shape
`submit_ce/ui/controllers/sword_license.py:46-50` reads is the same on master. That said, arxiv-base
is the shared dependency hub, so a bump is cross-cutting and needs the normal regression pass across
submit-ce rather than a drop-in swap. If the pin cannot move in this PR, say so in the PR
description — the chrome is non-compliant until it does.

### 3. The skip link can never become visible — owner: the same pin

At the pinned commit, `base/base.html` renders `<a href="#main-container" class="is-sr-only">Skip to
main content</a>`, and `.is-sr-only` (`arxiv-base/arxiv/base/static/css/arxivstyle.css:1248-1257`)
clips the element to 0.01em with `!important` and has **no `:focus` reveal**. The link is announced to
screen readers but is permanently invisible to sighted keyboard users.

`docs/public/header-styles.html` → Behavior contract: "The skip link (`.ds-skip-link`) is the first
focusable element on the page, **visible only on keyboard focus**."

**Fix.** Same pin bump. Master's `.ds-skip-link`
(`arxiv-base/arxiv/base/static/css/arxiv-header-footer.css:175-191`) moves to `top: 8px` on
`:focus-visible` at `z-index: 200` — which also matches the policy's z-layer scale ("skip
link/overlays 200").

### 4. Fonts load from Google Fonts — owner: arxiv-base, and **not** fixed by the pin bump

`arxiv-base/arxiv/base/static/css/arxivstyle.css:2`:

```css
@import url("https://fonts.googleapis.com/css?family=Open+Sans:400,400i,600,700");
```

`head.html:20` loads that stylesheet, so every page inheriting base chrome — including this one —
makes a third-party font request. Two policies:

- DESIGN-POLICIES → *Typography*: "**Self-hosted:** All fonts must be self-hosted from arXiv's
  static assets. No external font services (Google Fonts, Adobe Typekit, CDN-hosted fonts)."
- `AGENTS.md` → *Rules agents break most*: "**Self-hosted everything.** Never load fonts, icons, or
  CSS from external URLs — no Google Fonts, no CDNs. If an existing page does it, that page is wrong,
  not the rule."

The family is wrong as well as the delivery: `arxivstyle.css:300` sets `font-family: "Open Sans", …`,
while DESIGN-POLICIES → *Typography* allows "only IBM Plex Sans, IBM Plex Sans Condensed, IBM Plex
Mono, and STIX Two Math."

This is listed as blocking because the policy is unambiguous, but flagged plainly: it is not
actionable in this PR and it persists on arxiv-base master. It belongs in an arxiv-base issue —
self-host the Plex woff2 set with `font-display: swap` and drop the `@import`. Do not attempt it here.

## Should fix — token / brand / component drift

**Submit button is completely unstyled.** `sword_license.html:26` —
`<input type="submit" value="Set license" />` carries no class, and `arxivstyle.css` has no
`input[type="submit"]` selector (verified: no match), so it renders as a raw user-agent button.
DESIGN-POLICIES → *Buttons* requires 6px radius, 10px 20px padding, `0 1px 2px rgba(0,0,0,0.08)` at
rest, `transform: translateY(1px)` on `:active`, 0.12s/0.08s transitions; *Colors* locks the public
primary to Open Blue `#a5d6fe` with Repository Brown `#1c1a17` text (11.3:1).

Fix, in-repo: `class="button button-secondary"`, matching
`submit-ce/submit_ce/ui/templates/submit/license.html:67`. Be aware that this only reduces the drift
— Bulma's `.button` (`arxivstyle.css:143-152`) is `border-radius: 4px`, `box-shadow: none`, padding
`0.375em 0.625em` (≈6px 10px), none of which match the policy. Full compliance needs `.ds-btn
ds-btn-primary` from `design-system/docs/public/design-system.css`, which submit-ce does not ship at
all. That gap is worth a ticket of its own: no page in submit-ce can currently be token-compliant.

**Inline link is not underlined, and its colour is off-palette.** The "Discussion of Licenses" link
(`sword_license.html:21`) sits in body prose. `arxivstyle.css:317-321` sets
`a { color: #086db1; text-decoration: none; }`.

- DESIGN-POLICIES → *Accessibility*: "**Link underlines:** Inline links in body text must be
  underlined. Standalone navigation links may omit underlines."
  `docs/public/link-styles.html` gives the reason: "Color contrast against body text is only 3.0:1 in
  light mode — too marginal to rely on alone."
- DESIGN-POLICIES → *Colors*: "**Use the palette.** All colors must come from the documented palette
  in `docs/color-mapping.md`. Do not introduce one-off hex values." `#086db1` is not in the palette;
  Link Blue is `#1565c0`. Computed: `#086db1` is 5.48:1 on white, `#1565c0` is 5.75:1 — so this is
  palette drift, not a contrast failure. Both clear the 4.5:1 AA floor.

Fix: `text-decoration: underline; text-underline-offset: 2px;` and `var(--arxiv-link-blue)`. Owner is
arxiv-base for the global rule; a page-scoped override on this one anchor is the surgical option if
the global change is too broad for this PR.

**No `<h1>` on the page.** The first heading is `<h2>License Statement</h2>`
(`sword_license.html:20`); the rendered output contains zero `<h1>`. The WCAG 2.1 AA floor
DESIGN-POLICIES adopts covers programmatic structure (1.3.1), and the sibling template
`submit-ce/submit_ce/ui/templates/submit/base.html:18` renders an `<h1 class="title title-submit">`
for exactly this slot, so the in-repo convention is an h1. Stated honestly: DESIGN-POLICIES has no
explicit heading-level rule, so this is the WCAG floor plus in-repo consistency rather than a quoted
design-system line. Fix: promote to `<h1>` — it is the page's only top-level heading.

**`<br />` used as vertical spacing.** `sword_license.html:24` separates options with `<br />`, so
the rhythm is whatever line-height happens to be. DESIGN-POLICIES → *Spacing*: "**Scale.** Use the
4px-based / 8-point spacing scale … Don't introduce off-scale values" and "**Proximity.** The gap
*between* sections should be clearly larger than the gap *within* a section — aim for ~3×."
`docs/internal/form-styles.html` shows the intended construction: one label per line, grouped by
spacing from the scale, "no boxes or borders." Fix: drop the `<br />`, make each label
`display: block` with a `--space-*` gap, and put a larger gap before the submit row.

**Prose runs the full container width.** The explanatory paragraph is a direct child of
`<main class="container">`, which is 960px at ≥1088px and 1152px at ≥1280px
(`arxivstyle.css:2314-2345`). DESIGN-POLICIES → *Layout and content width*: "**Text respects the
measure.** Any block of continuous prose targets a ~65-character line length (~640–720px), on public
and internal surfaces alike." Fix: constrain the text block to `max-width: 65ch`.

**License radio group now exists twice.** The same control appears in `sword_license.html:23-25` and
`submit-ce/submit_ce/ui/templates/submit/license.html:137-208`. DESIGN-POLICIES → *Components*:
"**New patterns:** If a UI element appears in two or more pages, extract it into a design system CSS
file and create or update a pattern page in `docs/`." The two are already inconsistent — one has
labels, one does not, which is how finding 1 arose. Worth a follow-up ticket rather than in-PR work;
note it so the divergence is recorded.

## Consider — minor / stylistic

**Radio hit area.** Unstyled radios are ~13×13 CSS px against DESIGN-POLICIES → *Chrome and
interaction structure*: "**Target size.** Hard floor 24×24 CSS px (WCAG 2.2 SC 2.5.8 AA)." The policy
carries WCAG's own exceptions, explicitly including "user-agent defaults," and these controls are
entirely unstyled — so the exception plausibly applies as-is today. Flagging it because the exception
evaporates the moment any sizing is authored, and because the `<label>` fix in finding 1 grows the
effective target to the full text row for free.

**No `fieldset`/`legend` around the group.** `docs/internal/form-styles.html` uses
`<fieldset class="seg-control">` + `<legend class="sr-only">` for exclusive-choice groups, but that is
the segmented-control pattern, not a stated rule for radios — so this is pattern-adjacent, not a
policy citation. It would give the group an accessible name beyond the visible `<h2>`.

**FontAwesome is loaded.** `arxiv-base/arxiv/base/templates/base/head.html:19` loads
`fontawesome-free-5.11.2-web/js/all.js`, and the inherited footer uses FontAwesome SVG paths.
DESIGN-POLICIES → *Components*: "**Icons:** One icon language: inline SVG from the Lucide set … No
icon fonts." This page renders no icons of its own, so it is inherited-only, upstream, and low
priority — noted for completeness.

**Non-policy note:** `</input>` (line 24) is invalid HTML. No design policy covers it and no test
matches it; it disappears naturally if the `<label>` fix is applied.

## Compliant — worth noting

- **Chrome is inherited, not hand-built.** `AGENTS.md` → routing: "never hand-build chrome or draw
  logos from text." Extending `base/base.html` satisfies this, and is why finding 2 is a one-line
  dependency fix instead of a template rewrite.
- **Correct base template chosen.** Extending `base/base.html` rather than `submit/base.html` avoids
  the workflow progress bar and the `submission_id`/`workflow` context this page has none of.
- **Progressive enhancement.** The page is fully server-rendered and functional with JS off —
  DESIGN-POLICIES → "Server-rendered HTML is complete and readable before any JavaScript runs."
- **`<h2>` does render as a heading.** The `h1`–`h6` reset at `arxivstyle.css:222-231`
  (`font-size: 100%; font-weight: normal`) is overridden for content inside `<main>` by
  `arxivstyle.css:9994-9997` (`main h2 { font-size: 1.5em }`) plus `main h1,…h6 { font-weight: 600 }`.
  Worth stating explicitly because the reset looks alarming in isolation.
- **Landmarks and language.** Real `<header>`, `<main id="main-container">`, `<footer>`, and
  `<html lang="en">`.
- **No surface crossing.** No Access Lime anywhere — correct for a public page.
- **No sticky chrome**, no hand-picked dark-mode values, and no view/download/citation metrics.
