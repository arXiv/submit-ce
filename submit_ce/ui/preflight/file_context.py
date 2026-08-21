"""Assemble the per-file rows for the Review Files table. [SUBMISSION-219 / F0]

The ``display_preflight_tree`` macro used to compute everything about a file
inline: it looked the badges up in a separate ``file_issues`` dict and decided
"is this the 00README / a selected top-level file?" with string comparisons
against extra template parameters. Issue badges and file-use status,
delete default, both need to write that same "Auto-detected Notes" cell, so
without a single seam they conflict in the controller and the template.

This module provides that seam: it folds the per-file issue badges and the
top-level / README flags into each file object, so the template renders
fields from one object instead of computing them. The next phase will extend the object
(used/unused, delete defaults, image size) without touching Jinja.

Pure transform -- no I/O.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

# The build-directives file: not a deletion candidate, and it gets a dedicated
# note rather than a usage line.
README_FILENAME = "00README.json"


def build_file_rows(
    file_notes: List[Dict[str, Any]],
    file_issues: Optional[Dict[str, List[Dict[str, str]]]],
    selected_top_level_files: List[str],
    used_filenames: Optional[Set[str]] = None,
    toplevel_candidates: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Return the preflight file list enriched for the Review Files table.

    Each row keeps its preflight keys (``filename`` and, where present,
    ``used_by`` / ``used_by_tex`` / ``used_by_bib``) and gains:

    * ``badges`` -- per-file issue badges ``[{severity, label}, ...]`` (empty
      list when the file has none);
    * ``is_readme`` -- ``True`` for ``00README.json`` (build-directives file);
    * ``is_toplevel`` -- ``True`` when the file is a selected top-level TeX file;
    * ``is_used`` -- an ordinary file that is *needed by the selected top-level(s)*.
      When ``used_filenames`` is given (SUBMISSION-231) this is rooted membership
      in that set -- the files reachable from the selected top-level(s), so the
      classification changes as the selection changes. When it is ``None`` (older
      callers/tests) it falls back to "preflight resolved any reference to it"
      (the ``used_by*`` reverse edges), the pre-231 behavior;
    * ``is_maybe_used`` -- an ordinary file only in the coarse ``maybe_used_files``
      guess bucket (rendered "Possibly used");
    * ``is_unused`` -- an ordinary file nothing references (rendered "Not used").
      Auto-checked for deletion by the template -- EXCEPT for an unselected
      detected top-level candidate (see ``toplevel_candidates``), which is left
      unchecked;
    * ``is_protected`` -- must not be deleted here (readme, selected top-level, or
      confidently-used); drives the disabled delete checkbox.

    ``toplevel_candidates`` (SUBMISSION-244) is the set of preflight-detected
    top-level TeX files. A detected candidate the submitter has NOT selected is a
    plausible alternative "main" they may pick next, so it must never be
    *auto-checked* for deletion even when nothing currently references it: for
    such a file ``is_unused`` is cleared (it renders "Not used" but unchecked and
    still deletable). This mirrors the client-side live recompute and, crucially,
    protects the JavaScript-disabled path -- where nothing would otherwise
    uncheck it before Continue and the delete guard doesn't cover an unselected
    candidate.

    ``is_readme`` / ``is_toplevel`` / ``is_used`` / ``is_maybe_used`` / ``is_unused``
    are mutually exclusive and drive the usage note; ``is_protected`` drives the
    delete checkbox; ``badges`` render before the note. The input dicts are not
    mutated.

    Any other keys already on a file note are preserved unchanged -- e.g. the
    image size fields ``width`` / ``height`` / ``megapixels`` / ``is_oversized``
    that ``get_files_from_preflight`` attaches for image files (SUBMISSION-172). This is the point of the single per-file object: new per-file data is
    added upstream and flows through without touching this helper or the macro.
    """
    issues = file_issues or {}
    top_levels = set(selected_top_level_files or [])
    rows: List[Dict[str, Any]] = []
    for note in file_notes:
        row = dict(note)
        filename = row.get("filename")
        row["badges"] = issues.get(filename) or []
        row["is_readme"] = filename == README_FILENAME
        row["is_toplevel"] = filename in top_levels
        # Usage classification (SUBMISSION-221 / C3.2a), by descending confidence:
        #   is_used       -- needed by the selected top-level(s);
        #   is_maybe_used -- only in the coarse maybe_used_files guess bucket;
        #   is_unused     -- nothing references it at all ("Not used").
        # A resolved edge wins over the maybe-used flag. The 00README and a
        # selected top-level are handled separately and are none of these.
        #
        # "used" is rooted at the current selection when `used_filenames` is
        # supplied (SUBMISSION-231): membership in the set of files reachable
        # from the selected top-level(s), so the note flips as the top-level
        # changes. Without it (older callers), fall back to the flat "referenced
        # by any tex file" signal (the used_by* reverse edges) -- the pre-231
        # behavior, preserved so existing callers/tests are unaffected.
        raw_maybe_used = bool(row.get("is_maybe_used"))
        if used_filenames is not None:
            used_refs = filename in used_filenames
        else:
            used_refs = bool(row.get("used_by")
                             or row.get("used_by_tex")
                             or row.get("used_by_bib"))
        ordinary = not row["is_readme"] and not row["is_toplevel"]
        row["is_used"] = ordinary and used_refs
        row["is_maybe_used"] = ordinary and not used_refs and raw_maybe_used
        row["is_unused"] = ordinary and not used_refs and not raw_maybe_used
        # An unselected detected top-level candidate is a plausible alternative
        # "main" the submitter may pick next -- never auto-check it for deletion,
        # even when unreferenced. Clear is_unused so the template renders it
        # "Not used" but UNCHECKED; it stays deletable if the submitter opts in.
        # Protects the no-JS path (SUBMISSION-244 / SUBMISSION-231).
        if (toplevel_candidates and row["is_unused"]
                and filename in toplevel_candidates):
            row["is_unused"] = False
        # Protected from deletion (C3.2a): the 00README, a selected top-level, or
        # a confidently-used file. maybe-used and unused files stay deletable.
        row["is_protected"] = row["is_readme"] or row["is_toplevel"] or row["is_used"]
        rows.append(row)
    return rows
