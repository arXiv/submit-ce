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

from typing import Any, Dict, List, Optional, Set, Tuple

from submit_ce.ui.preflight.issue_table import (
    ALWAYS_ACT,
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
    used_filenames: Optional[Set[str]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, str]]]]:
    """Return ``(notifications, file_issues)`` for the Review Files template.

    ``notifications`` -- one dict per reason-code group, ordered danger-first:
    ``{title, severity, body, url?, link_text?}`` for the existing
    ``immediate_notifications`` loop.

    ``file_issues`` -- ``{filename: [{severity, label}, ...]}`` for per-row
    badges in the Notes column.

    Silent codes are skipped entirely (banners and badges), matching 1.5.

    Severity-by-usage (SUBMISSION-247): when ``used_filenames`` is given (the set
    of files reachable from the selected top-level(s), including the selected
    top-levels themselves), a ``danger`` issue whose carrying file is NOT in that
    set is downgraded to a non-blocking ``warning`` -- the file won't be
    compiled, so its errors shouldn't block. Codes in ``ALWAYS_ACT``
    (pdf_javascript, pdf_not_pdf, ...) are never downgraded. Issues with no file
    attribution, and everything when ``used_filenames`` is ``None`` (older
    callers), are left unchanged. A single info nudge lists the unused files that
    carried downgraded issues, so the submitter is prompted to remove them.
    """
    notifications: List[Dict[str, Any]] = []
    file_issues: Dict[str, List[Dict[str, str]]] = {}
    if not preflight_data:
        return notifications, file_issues

    groups: Dict[str, Dict[str, Any]] = {}
    downgraded_files: List[str] = []
    all_issues = list(_iter_issues(preflight_data)) + \
        list(_derived_issues(preflight_data))
    for key, info, filename, container in all_issues:
        if not key:
            continue
        severity = _directive(key).get("severity", "warning")
        if severity == SILENT:
            continue

        if key in _REFERENCED_FILE_CODES:
            # The named file is a *missing* file (not the carrier); list it in
            # the banner but never badge -- it has no row, and the carrier is
            # fine. Usage is judged by the carrier (the referencing file).
            subject = filename or info
            badge_target = None
            owner = container
        else:
            # The issue is about the carrying file (or its own filename).
            subject = filename or container
            badge_target = subject
            owner = subject

        # SUBMISSION-247: downgrade a danger issue to non-blocking when its file
        # is not used by the selected top-level(s) and the code isn't always-act.
        effective = severity
        if (used_filenames is not None and severity == "danger"
                and key not in ALWAYS_ACT
                and owner and owner not in used_filenames):
            effective = "warning"
            if owner not in downgraded_files:
                downgraded_files.append(owner)

        group = groups.setdefault(
            key, {"count": 0, "files": [], "severity": effective})
        group["count"] += 1
        # The group takes the most severe effective severity among its issues,
        # so a code present in BOTH a used and an unused file still blocks.
        if _SEVERITY_RANK.get(effective, 9) < _SEVERITY_RANK.get(group["severity"], 9):
            group["severity"] = effective

        if subject and subject not in group["files"]:
            group["files"].append(subject)
        if badge_target:
            file_issues.setdefault(badge_target, []).append(
                {"severity": effective, "label": _humanize(key)})

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

    # SUBMISSION-247: nudge the submitter to remove the unused files whose issues
    # we downgraded (they're already auto-checked for deletion, SUBMISSION-222).
    if downgraded_files:
        notifications.append({
            "title": "Some problems are in files your selected top-level "
                     "doesn't use",
            "severity": "info",
            "body": "These files aren't part of the selected compilation, so "
                    "their problems no longer block you -- consider removing "
                    "them: " + ", ".join(downgraded_files),
        })

    return notifications, file_issues


def has_blocking_issues(preflight_data: Optional[dict],
                        used_filenames: Optional[Set[str]] = None) -> bool:
    """Return True if any surfaced preflight issue is ``danger`` severity.

    Mirrors 1.5's ``hasPreflightBlockers``: a ``danger`` issue must block the
    submitter from continuing past Review Files. Silent/warning/info issues do
    not block. (SUBMISSION-216 / C1.4)

    Passing ``used_filenames`` makes the gate selection-aware (SUBMISSION-247):
    a danger issue in a file the selected top-level doesn't use is downgraded
    and no longer blocks (unless its code is in ``ALWAYS_ACT``).
    """
    notifications, _ = build_issue_context(preflight_data, used_filenames)
    return any(n.get("severity") == "danger" for n in notifications)


# Order + headings for the consolidated per-severity issue cards (C1.6).
_SEVERITY_ORDER = ("danger", "warning", "info")
_SEVERITY_HEADINGS = {
    "danger": "Errors",
    "warning": "Warnings",
    "info": "For your information",
}


def group_notifications_by_severity(
    notifications: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Collapse the per-code issue notifications into one card per severity.

    Instead of one banner per reason code, return at most three cards -- danger,
    then warning, then info -- each carrying the individual issues as ``issues``
    (``{text, body, url?, link_text?}``). Restores 1.5's severity-zone grouping
    (danger/warning/neutral message areas). (SUBMISSION-218 / C1.6)
    """
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for n in notifications:
        buckets.setdefault(n.get("severity", "warning"), []).append({
            "text": n.get("title", ""),
            "body": n.get("body", ""),
            "url": n.get("url"),
            "link_text": n.get("link_text"),
        })
    grouped: List[Dict[str, Any]] = []
    for severity in _SEVERITY_ORDER:
        if buckets.get(severity):
            grouped.append({
                "severity": severity,
                "title": _SEVERITY_HEADINGS[severity],
                # NB: key is 'issues', NOT 'items' -- in Jinja `x.items` on a dict
                # resolves to the built-in dict.items method, breaking the template.
                "issues": buckets[severity],
            })
    return grouped
