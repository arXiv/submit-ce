"""Table of preflight issues, severities, and user-facing messages.

This is the single source of truth for **how each preflight issue is presented**
on the Review Files page: its severity (which controls whether the submitter is
blocked) and the message shown to the submitter. It ports Submit 1.5's
client-side ``PreflightDirectives`` table (``actionsAddFiles.js``) to the server
so issues render in Jinja with no JavaScript.

Background: the preflight producer (``tex2pdf_tools``) emits each issue as
``{key, info, filename?}`` with **no severity** and, for several codes, **no
user-ready message**. Severity and copy are therefore owned here.

Severity vocabulary (maps to a Bulma modifier: ``notification is-<severity>``):

* ``danger``  -- a blocking problem; the submitter cannot continue (1.5 set
                 ``hasPreflightBlockers`` on these and disabled Continue).
* ``warning`` -- the submitter is warned but may continue.
* ``info``    -- informational only (1.5 called this ``neutral``).
* ``silent``  -- collected but never shown (as in 1.5).

Provenance of each row (see the inline comments):

* codes WITHOUT a ``# NEW`` comment mirror 1.5's table (severity == 1.5's);
* codes marked ``# NEW`` did not exist in 1.5's table -- their severity/copy are
  **proposed** and pending team review (SUBMISSION-211);
* one severity intentionally **differs** from current 1.5 (``no_top_level_file``,
  marked ``# CHANGED``): 1.5 keeps it silent; we surface it as a blocking danger.

The ``message`` may contain the token ``{n}``, replaced at render time by the
count of issues with that code. Links are kept as separate, trusted, static
fields (``url``/``link_text``) so no untrusted producer text is rendered as HTML.
"""
from __future__ import annotations

from typing import Any, Dict

SILENT = "silent"

# Severity ordering for danger-first grouping in the banner area.
SEVERITY_RANK = {"danger": 0, "warning": 1, "info": 2}

# reason code -> {severity, message?, url?, link_text?}
PREFLIGHT_ISSUE_DIRECTIVES: Dict[str, Dict[str, Any]] = {
    # --- bibliography ---
    "bbl_version_mismatch": {
        "severity": "danger",
        "message": "The scan found a .bbl file built with an unsupported "
                   "version. Rebuild it, or select a matching TeX Live version.",
    },
    "bbl_version_needs_previous_version": {  # NEW since 1.5 (proposed)
        "severity": "warning",
        "message": "Your .bbl file was built with an older BibTeX and needs "
                   "TeX Live 2023. Select TeX Live 2023, or regenerate the .bbl.",
    },
    "multiple_bibliography_types": {  # matches current 1.5 (danger); 1.5 blocks on missing/mismatched bibliography (commit ada6b18a)
        "severity": "danger",
        "message": "The scan detected multiple bibliography types. Please use a "
                   "single bibliography method.",
    },
    "bbl_usage_mismatch": {  # matches current 1.5 (danger); 1.5 blocks on missing/mismatched bibliography (commit ada6b18a)
        "severity": "danger",
        "message": "The scan found a .bbl/.bib processor mismatch (for example a "
                   "biber .bbl used with bibtex). Regenerate the .bbl with the "
                   "correct tool.",
    },
    "bbl_file_missing": {
        "severity": "warning",
        "message": "The scan did not find an expected .bbl file.",
    },
    "bbl_bib_file_missing": {  # matches current 1.5 (danger); 1.5 blocks on missing/mismatched bibliography (commit ada6b18a)
        "severity": "danger",
        "message": "The scan did not detect a bibliography. Please include one.",
    },
    # --- conflicting types ---
    "conflicting_engine_type": {
        "severity": "danger",
        "message": "The scan detected conflicting TeX engines across your files.",
    },
    "conflicting_file_type": {
        "severity": "danger",
        "message": r"The scan detected use of \bye in an otherwise LaTeX "
                   r"document; please use \end{document} instead.",
    },
    "conflicting_image_types": {
        "severity": "warning",
        "message": "The scan detected conflicting image types.",
    },
    "conflicting_postprocess_type": {
        "severity": "danger",
        "message": "The scan detected conflicting post-processing types.",
    },
    "conflicting_output_type": {
        # NOTE: currently never emitted by the producer (overwrite bug in
        # guess_compilation_parameters); severity retained for when it is fixed.
        "severity": "warning",
        "message": "The scan detected conflicting output types (for example "
                   "pdfoutput set to both 0 and 1).",
    },
    # --- compiler support ---
    "unsupported_compiler_type": {
        "severity": "danger",
        "message": "The submission requires a compiler that is not available at "
                   "arXiv. Please modify your source files to compile under our "
                   "processors and re-upload.",
        "url": "https://info.arxiv.org/help/submit_tex.html#supported-processors",
        "link_text": "Read about arXiv's supported processing",
    },
    "unsupported_compiler_type_latex209": {  # matches current 1.5 (danger); compiler unavailable at arXiv
        "severity": "danger",
        "message": "LaTeX 2.09 is no longer supported. Please update your source "
                   "to a supported LaTeX and re-upload.",
        "url": "https://info.arxiv.org/help/submit_tex.html#supported-processors",
        "link_text": "Read about arXiv's supported processing",
    },
    "unsupported_compiler_type_image_mix": {  # matches current 1.5 (danger); compiler unavailable at arXiv
        "severity": "danger",
        "message": "The scan detected a mix of image types requiring conflicting "
                   "compilers. Use a single image family and re-upload.",
        "url": "https://info.arxiv.org/help/submit_tex.html#supported-processors",
        "link_text": "Read about arXiv's supported processing",
    },
    "unsupported_compiler_type_unicode": {  # matches current 1.5 (danger); compiler unavailable at arXiv
        "severity": "danger",
        "message": "The submission requires a Unicode TeX engine (XeTeX or "
                   "LuaTeX) that is not available at arXiv. In these cases please "
                   "contact user support to request an exemption to submit PDF.",
        "url": "https://arxiv.org/help/contact",
        "link_text": "arXiv user support",
    },
    # --- other source checks ---
    "file_not_found": {
        "severity": "warning",
        "message": "The scan detected {n} file(s) missing from the source. "
                   "Please upload the missing file(s). If a file is already "
                   "present, uncheck its row below to mark it as used.",
    },
    "include_command_with_macro": {"severity": SILENT},
    "contents_decode_error": {
        "severity": "warning",
        "message": "The scan could not decode the contents of {n} file(s).",
    },
    "issue_in_subfile": {"severity": SILENT},
    "index_definition_missing": {
        "severity": "warning",
        "message": "The scan did not find an expected index definition.",
    },
    "oversized_image": {  # NEW since 1.5 (proposed)
        "severity": "warning",
        "message": "The scan found {n} oversized image(s) (over 34 megapixels). "
                   "Large images can slow or block processing; consider reducing "
                   "them.",
    },
    "pdf_not_pdf": {  # NEW since 1.5 (proposed); danger (unusable file)
        "severity": "danger",
        "message": "The scan found {n} file(s) that do not look like valid PDFs.",
    },
    "pdf_javascript": {  # NEW since 1.5; danger -- arXiv rejects JS-bearing PDFs; UI blocks (tex2pdf currently keeps the PDF, so blocking here is required). Revisit to warning if the service deletes JS PDFs.
        "severity": "danger",
        "message": "The scan found JavaScript embedded in {n} PDF(s). arXiv does "
                   "not accept PDFs containing JavaScript.",
    },
    "graphics_driver_option": {  # NEW since 1.5 (no precedent); proposed info
        "severity": "info",
        "message": "A graphics package was loaded with an explicit driver "
                   "option; this can cause issues under our processors.",
    },
    "graphics_driver_unsupported": {  # NEW since 1.5 (proposed)
        "severity": "warning",
        "message": "A graphics package was loaded with an unsupported driver "
                   "option. Please remove or change it and re-upload.",
    },
    "unsupported_zzrm_format": {  # NEW since 1.5; danger (decided in review) -- block until the unsupported 00README is converted to .json, rather than silently ignoring it
        "severity": "danger",
        "message": "Your 00README format is no longer supported; only "
                   "00README.json is accepted.",
    },
    # --- derived: the producer no longer emits these as issues ---
    # hyperref_not_found is now a boolean (ToplevelFile.hyperref_found); the
    # extractor synthesizes the issue from it.
    # SILENT per team review of the C1.6 cards reorg (2026-08-05): the "hyperref
    # is no longer auto-loaded" notice is a migration reminder that has been shown
    # for a long time and no longer needs repeating on every submission. Kept the
    # message text below for provenance / easy revert if we want to resurface it.
    "hyperref_not_found": {
        "severity": SILENT,
        "message": "arXiv's TeX processing no longer loads the hyperref package "
                   "automatically (it once did). If your document relies on "
                   r"hyperref, add \usepackage{hyperref} to your source and "
                   "re-upload.",
    },
    # no_top_level_file: 1.5 kept this silent (deferred to a legacy system
    # message). 2.0 has no such message and the flow already blocks advancing
    # without a top-level, so we surface it as a blocking danger with a reason.
    "no_top_level_file": {  # CHANGED: 1.5 silent; danger (cannot compile) -- DECIDED blocking
        "severity": "danger",
        "message": "The scan did not detect a viable top-level TeX file. Upload "
                   "your main (La)TeX file and try again.",
    },
    # --- generic catch-all ---
    "other": {
        "severity": "warning",
        "message": "The scan detected {n} other issue(s).",
    },
}

# Unknown codes (e.g. plugin-defined) fall back to a visible warning.
DEFAULT_DIRECTIVE: Dict[str, Any] = {"severity": "warning", "message": None}


def directive_for(key: str) -> Dict[str, Any]:
    """Return the presentation directive for an issue code (or the default)."""
    return PREFLIGHT_ISSUE_DIRECTIVES.get(key, DEFAULT_DIRECTIVE)
