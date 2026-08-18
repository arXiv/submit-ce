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

from typing import Any, Dict, List, Optional

# The build-directives file: not a deletion candidate, and it gets a dedicated
# note rather than a usage line.
README_FILENAME = "00README.json"


def build_file_rows(
    file_notes: List[Dict[str, Any]],
    file_issues: Optional[Dict[str, List[Dict[str, str]]]],
    selected_top_level_files: List[str],
) -> List[Dict[str, Any]]:
    """Return the preflight file list enriched for the Review Files table.

    Each row keeps its preflight keys (``filename`` and, where present,
    ``used_by`` / ``used_by_tex`` / ``used_by_bib``) and gains:

    * ``badges`` -- per-file issue badges ``[{severity, label}, ...]`` (empty
      list when the file has none);
    * ``is_readme`` -- ``True`` for ``00README.json`` (build-directives file);
    * ``is_toplevel`` -- ``True`` when the file is a selected top-level TeX file;
    * ``is_used`` -- an ordinary file preflight resolved a reference to;
    * ``is_maybe_used`` -- an ordinary file only in the coarse ``maybe_used_files``
      guess bucket (rendered "Possibly used");
    * ``is_unused`` -- an ordinary file nothing references (rendered "Not used");
    * ``is_protected`` -- must not be deleted here (readme, selected top-level, or
      confidently-used); drives the disabled delete checkbox.

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
        #   is_used       -- preflight resolved a reference to it (used_by* edges);
        #   is_maybe_used -- only in the coarse maybe_used_files guess bucket;
        #   is_unused     -- nothing references it at all ("Not used").
        # A resolved edge wins over the maybe-used flag. The 00README and a
        # selected top-level are handled separately and are none of these.
        raw_maybe_used = bool(row.get("is_maybe_used"))
        used_refs = bool(row.get("used_by")
                         or row.get("used_by_tex")
                         or row.get("used_by_bib"))
        ordinary = not row["is_readme"] and not row["is_toplevel"]
        row["is_used"] = ordinary and used_refs
        row["is_maybe_used"] = ordinary and not used_refs and raw_maybe_used
        row["is_unused"] = ordinary and not used_refs and not raw_maybe_used
        # Protected from deletion (C3.2a): the 00README, a selected top-level, or
        # a confidently-used file. maybe-used and unused files stay deletable.
        row["is_protected"] = row["is_readme"] or row["is_toplevel"] or row["is_used"]
        rows.append(row)
    return rows
