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
    * ``is_unused`` -- ``True`` for an ordinary file that nothing references
      (rendered as "Not used").

    ``is_readme`` / ``is_toplevel`` drive both the disabled delete checkbox and
    the usage note; ``is_unused`` drives the "Not used" note; ``badges`` render
    before the note. The input dicts are not mutated.

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
        # Unused = an ordinary file (not the 00README, not a selected top-level)
        # that no TeX/bib file references. These render "Not used", mirroring 1.5
        # (SUBMISSION-220). Display only -- this does not (yet) pre-check
        # the delete box; that comes later, gated on the delete-of-used policy.
        row["is_unused"] = (
            not row["is_readme"]
            and not row["is_toplevel"]
            and not (row.get("used_by")
                     or row.get("used_by_tex")
                     or row.get("used_by_bib"))
        )
        rows.append(row)
    return rows
