"""Extract preflight issues from a preflight payload for the Review Files page.

[SUBMISSION-210] Consumes the presentation table in ``preflight_issue_table`` to
turn a preflight response into two things for the Review Files template:

* **page-level notifications** grouped by reason code, shaped for the existing
  ``immediate_notifications`` loop; and
* **per-file issue badges** for the "Auto-detected Notes" column.

The severity/message table itself lives in ``preflight_issue_table`` (reviewed
separately under SUBMISSION-211); this module is only the extraction logic.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from submit_ce.ui.controllers.new.preflight_issue_table import (
    DEFAULT_DIRECTIVE,
    PREFLIGHT_ISSUE_DIRECTIVES,
    SEVERITY_RANK,
    SILENT,
    directive_for,
)

# Backwards-compatible aliases for existing references within this module.
_directive = directive_for
_SEVERITY_RANK = SEVERITY_RANK

# Codes whose named file is a *referenced / missing* file rather than the file
# that carries the issue. For these, the name (issue.filename or issue.info)
# identifies a file that is NOT in the source, so it must NOT be attributed to
# the carrying file (that file exists) and gets no per-row badge -- it is only
# named in the banner. Producer: file_not_found is raised on the referencing
# node with the missing name in `info` (preflight/__init__.py:1307) or in
# `filename` for the bib variant (:1589).
_REFERENCED_FILE_CODES = {"file_not_found"}


def _humanize(key: str) -> str:
    return key.replace("_", " ")


def _directive(key: str) -> Dict[str, Any]:
    return PREFLIGHT_ISSUE_DIRECTIVES.get(key, DEFAULT_DIRECTIVE)


def _iter_issues(preflight_data: dict):
    """Yield ``(key, info, filename, container)`` for every issue in the payload.

    Issues live at two levels in a ``PreflightResponse``:
    ``detected_toplevel_files[].issues`` (document-level) and
    ``tex_files[].issues`` (per source file). ``filename`` is the issue's own
    filename (often unset); ``container`` is the ``tex_file`` that carries it
    (``None`` for document-level issues). Keeping them distinct matters for
    referenced-file codes (see ``_REFERENCED_FILE_CODES``).
    """
    for tlf in preflight_data.get("detected_toplevel_files") or []:
        for issue in tlf.get("issues") or []:
            yield issue.get("key"), issue.get("info"), issue.get("filename"), None
    for tex_file in preflight_data.get("tex_files") or []:
        container = tex_file.get("filename")
        for issue in tex_file.get("issues") or []:
            yield (issue.get("key"), issue.get("info"),
                   issue.get("filename"), container)


def _derived_issues(preflight_data: dict):
    """Issues we synthesize because the producer no longer emits them.

    Currently just ``hyperref_not_found``: any detected top-level file whose
    ``hyperref_found`` is explicitly ``False``.
    """
    toplevels = preflight_data.get("detected_toplevel_files") or []
    if any(tlf.get("hyperref_found") is False for tlf in toplevels):
        yield "hyperref_not_found", None, None, None


def build_issue_context(
    preflight_data: Optional[dict],
) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, str]]]]:
    """Return ``(notifications, file_issues)`` for the Review Files template.

    ``notifications`` -- one dict per reason-code group, ordered danger-first:
    ``{title, severity, body, url?, link_text?}`` for the existing
    ``immediate_notifications`` loop.

    ``file_issues`` -- ``{filename: [{severity, label}, ...]}`` for per-row
    badges in the Notes column.

    Silent codes are skipped entirely (banners and badges), matching 1.5.
    """
    notifications: List[Dict[str, Any]] = []
    file_issues: Dict[str, List[Dict[str, str]]] = {}
    if not preflight_data:
        return notifications, file_issues

    groups: Dict[str, Dict[str, Any]] = {}
    all_issues = list(_iter_issues(preflight_data)) + \
        list(_derived_issues(preflight_data))
    for key, info, filename, container in all_issues:
        if not key:
            continue
        severity = _directive(key).get("severity", "warning")
        if severity == SILENT:
            continue
        group = groups.setdefault(
            key, {"count": 0, "files": [], "severity": severity})
        group["count"] += 1

        if key in _REFERENCED_FILE_CODES:
            # The named file is a *missing* file (not the carrier); list it in
            # the banner but never badge -- it has no row, and the carrier is
            # fine.
            subject = filename or info
            badge_target = None
        else:
            # The issue is about the carrying file (or its own filename).
            subject = filename or container
            badge_target = subject

        if subject and subject not in group["files"]:
            group["files"].append(subject)
        if badge_target:
            file_issues.setdefault(badge_target, []).append(
                {"severity": severity, "label": _humanize(key)})

    for key in sorted(groups,
                      key=lambda k: (_SEVERITY_RANK.get(groups[k]["severity"], 9), k)):
        group = groups[key]
        directive = _directive(key)
        message = directive.get("message") or f"{_humanize(key)} ({{n}} issue(s))"
        notification: Dict[str, Any] = {
            "title": message.replace("{n}", str(group["count"])),
            "severity": group["severity"],
            "body": ("Affected file(s): " + ", ".join(group["files"]))
                    if group["files"] else "",
        }
        if directive.get("url"):
            notification["url"] = directive["url"]
            notification["link_text"] = directive.get("link_text", "Learn more")
        notifications.append(notification)

    return notifications, file_issues
