"""Tests for :mod:`submit_ce.ui.preflight.issues`. [SUBMISSION-210]"""

import pytest

from submit_ce.ui.preflight.issues import (
    PREFLIGHT_ISSUE_DIRECTIVES,
    build_issue_context,
    has_blocking_issues,
    group_notifications_by_severity,
)


def _pf(*keys):
    """Minimal preflight payload carrying the given issue codes on the top-level."""
    return {
        "detected_toplevel_files": [
            {"filename": "main.tex",
             "issues": [{"key": k, "info": ""} for k in keys]}
        ],
        "tex_files": [],
    }


# --- SUBMISSION-216 / C1.4: has_blocking_issues (danger blocks Continue) ---------

def test_has_blocking_issues_true_for_danger_code():
    assert has_blocking_issues(_pf("conflicting_file_type")) is True


def test_has_blocking_issues_false_for_warning_only():
    assert has_blocking_issues(_pf("file_not_found")) is False


def test_has_blocking_issues_false_for_silent_or_empty_or_none():
    assert has_blocking_issues(_pf("issue_in_subfile")) is False  # silent
    assert has_blocking_issues(_pf()) is False
    assert has_blocking_issues(None) is False


def test_has_blocking_issues_true_when_danger_mixed_with_warning():
    assert has_blocking_issues(_pf("file_not_found", "conflicting_file_type")) is True


# --- SUBMISSION-218 / C1.6: group_notifications_by_severity -----------------------

def test_group_notifications_buckets_and_orders():
    flat = [
        {"title": "W1", "severity": "warning", "body": "files: a"},
        {"title": "D1", "severity": "danger", "body": ""},
        {"title": "I1", "severity": "info", "body": ""},
        {"title": "W2", "severity": "warning", "body": ""},
    ]
    grouped = group_notifications_by_severity(flat)
    # one card per present severity, danger-first
    assert [g["severity"] for g in grouped] == ["danger", "warning", "info"]
    danger, warning, info = grouped
    assert danger["issues"][0]["text"] == "D1"
    assert len(warning["issues"]) == 2
    assert warning["issues"][0]["body"] == "files: a"
    assert all(g["title"] for g in grouped)  # each card has a severity heading


def test_group_notifications_empty_returns_empty():
    assert group_notifications_by_severity([]) == []


def test_group_notifications_single_severity_one_card():
    grouped = group_notifications_by_severity(
        [{"title": "D", "severity": "danger", "body": ""}])
    assert len(grouped) == 1
    assert grouped[0]["severity"] == "danger"
    assert grouped[0]["issues"][0]["text"] == "D"


def test_group_notifications_end_to_end_from_build_issue_context():
    # A danger + a warning code -> exactly two grouped cards, danger first.
    notifications, _ = build_issue_context(
        _pf("conflicting_file_type", "file_not_found"))
    grouped = group_notifications_by_severity(notifications)
    assert [g["severity"] for g in grouped] == ["danger", "warning"]


# --- SUBMISSION-247: severity by usage --------------------------------------

def _pf_texfile(filename, *keys):
    """Preflight payload where `keys` issues are carried by tex_file `filename`."""
    return {
        "detected_toplevel_files": [],
        "tex_files": [
            {"filename": filename,
             "issues": [{"key": k, "info": ""} for k in keys]}
        ],
    }


def test_danger_in_unused_file_downgraded_to_non_blocking():
    """A danger issue whose file isn't used by the selection is downgraded to a
    non-blocking warning, and a nudge lists the file (SUBMISSION-247)."""
    pf = _pf_texfile("draft-old.tex", "conflicting_file_type")
    assert has_blocking_issues(pf, used_filenames=set()) is False

    notes, file_issues = build_issue_context(pf, used_filenames=set())
    assert file_issues["draft-old.tex"][0]["severity"] == "warning"
    assert any(n["severity"] == "info" and "draft-old.tex" in n["body"]
               for n in notes)


def test_danger_in_used_file_still_blocks():
    pf = _pf_texfile("main.tex", "conflicting_file_type")
    assert has_blocking_issues(pf, used_filenames={"main.tex"}) is True
    _, file_issues = build_issue_context(pf, used_filenames={"main.tex"})
    assert file_issues["main.tex"][0]["severity"] == "danger"


def test_same_danger_code_in_used_and_unused_files_still_blocks():
    """If a code appears in both a used and an unused file, the group keeps the
    most severe (danger) so it still blocks."""
    pf = {
        "detected_toplevel_files": [],
        "tex_files": [
            {"filename": "main.tex",
             "issues": [{"key": "conflicting_file_type", "info": ""}]},
            {"filename": "draft.tex",
             "issues": [{"key": "conflicting_file_type", "info": ""}]},
        ],
    }
    assert has_blocking_issues(pf, used_filenames={"main.tex"}) is True


def test_always_act_code_blocks_even_in_unused_file():
    """Safety/policy codes (pdf_javascript, pdf_not_pdf) block regardless of
    whether the file is used (SUBMISSION-247)."""
    for code in ("pdf_javascript", "pdf_not_pdf"):
        pf = _pf_texfile("orphan.pdf", code)
        assert has_blocking_issues(pf, used_filenames=set()) is True, code


def test_without_used_filenames_no_downgrade_pre247_behavior():
    """Older callers that pass no used set get the pre-247 behavior unchanged."""
    pf = _pf_texfile("draft-old.tex", "conflicting_file_type")
    assert has_blocking_issues(pf) is True


def test_document_level_danger_attributed_to_its_top_level():
    """A document-level danger (e.g. conflicting_file_type) is carried by the
    top-level it was detected on, so it downgrades when THAT top-level isn't
    selected and blocks when it is (SUBMISSION-247). Mirrors real preflight,
    which reports conflicting_file_type at document level on the top-level."""
    pf = {
        "detected_toplevel_files": [
            {"filename": "main_good.tex", "issues": []},
            {"filename": "main_bad.tex",
             "issues": [{"key": "conflicting_file_type", "info": ""}]},
        ],
        "tex_files": [],
    }
    # main_bad selected -> its danger blocks
    assert has_blocking_issues(pf, {"main_bad.tex"}) is True
    # main_good selected -> main_bad's danger is in an unused top-level -> downgrade
    assert has_blocking_issues(pf, {"main_good.tex"}) is False
    notes, file_issues = build_issue_context(pf, {"main_good.tex"})
    assert file_issues["main_bad.tex"][0]["severity"] == "warning"
    assert any(n["severity"] == "info" and "main_bad.tex" in n["body"]
               for n in notes)


def test_directives_cover_every_producer_issue_type():
    """Every IssueType the preflight producer can emit has a directive, so new
    producer codes can't silently fall through to the default unnoticed."""
    from tex2pdf_tools.preflight.models import IssueType
    missing = [it.value for it in IssueType
               if it.value not in PREFLIGHT_ISSUE_DIRECTIVES]
    assert missing == [], f"IssueType codes without a directive: {missing}"


def test_empty_and_none_preflight_yield_nothing():
    assert build_issue_context(None) == ([], {})
    assert build_issue_context({}) == ([], {})


def test_file_not_found_names_missing_files_not_the_carrier():
    """file_not_found is raised on the *referencing* file with the missing name
    in `info` (producer __init__.py:1307) or in `filename` for the bib variant
    (:1589). The banner must name the MISSING files, never badge the existing
    carrier as if it were missing (regression: an existing top-level file was
    labelled 'file not found')."""
    preflight = {
        'tex_files': [
            {'filename': 'main.tex',
             'issues': [
                 {'key': 'file_not_found', 'info': 'a.sty'},           # :1307
                 {'key': 'file_not_found', 'info': 'bib file missing',
                  'filename': 'refs.bib'},                              # :1589
             ]},
        ],
    }
    notifications, file_issues = build_issue_context(preflight)

    assert len(notifications) == 1
    note = notifications[0]
    assert note['severity'] == 'warning'
    assert '2 file(s) missing' in note['title']            # {n} substituted
    # Banner names the missing files, not the carrier.
    assert 'a.sty' in note['body'] and 'refs.bib' in note['body']
    assert 'main.tex' not in note['body']
    # No per-file badge: the missing files have no row, the carrier is fine.
    assert file_issues == {}


def test_per_file_badge_attaches_to_the_real_file():
    """For non-referenced codes, the badge attaches to the issue's own file."""
    preflight = {
        'detected_toplevel_files': [
            {'filename': 'main.tex',
             'issues': [{'key': 'oversized_image', 'info': 'x',
                         'filename': 'big.png'}]},
        ],
    }
    _, file_issues = build_issue_context(preflight)
    assert file_issues['big.png'][0] == {'severity': 'warning',
                                        'label': 'oversized image'}


def test_silent_codes_are_skipped_everywhere():
    preflight = {
        'tex_files': [
            {'filename': 'main.tex',
             'issues': [{'key': 'issue_in_subfile', 'info': '1',
                         'filename': 'sub.tex'}]},
        ],
    }
    notifications, file_issues = build_issue_context(preflight)
    assert notifications == []
    assert file_issues == {}


def test_hyperref_not_found_is_silent():
    """hyperref_not_found is derived from ToplevelFile.hyperref_found == False,
    but is SILENT (SUBMISSION-218 review, 2026-08-05): the migration reminder is
    no longer surfaced, so it produces neither a banner nor a per-file badge."""
    preflight = {
        'detected_toplevel_files': [
            {'filename': 'main.tex', 'hyperref_found': False, 'issues': []},
        ],
    }
    notifications, file_issues = build_issue_context(preflight)
    assert notifications == []
    assert file_issues == {}


def test_unsupported_compiler_carries_learn_more_link():
    preflight = {
        'detected_toplevel_files': [
            {'filename': 'main.tex',
             'issues': [{'key': 'unsupported_compiler_type', 'info': 'x'}]},
        ],
    }
    notifications, _ = build_issue_context(preflight)
    note = notifications[0]
    assert note['severity'] == 'danger'
    assert note['url'].startswith('https://')
    assert note['link_text']


def test_notifications_ordered_danger_first():
    preflight = {
        'detected_toplevel_files': [
            {'filename': 'main.tex',
             'issues': [{'key': 'oversized_image', 'info': 'x', 'filename': 'f.png'},
                        {'key': 'bbl_bib_file_missing', 'info': 'y'}]},
        ],
    }
    notifications, _ = build_issue_context(preflight)
    severities = [n['severity'] for n in notifications]
    assert severities == ['danger', 'warning']


def test_tex_file_issue_without_filename_uses_container():
    """A per-file issue with no explicit filename is attributed to the tex file
    that carries it."""
    preflight = {
        'tex_files': [
            {'filename': 'main.tex',
             'issues': [{'key': 'conflicting_file_type', 'info': 'z'}]},
        ],
    }
    _, file_issues = build_issue_context(preflight)
    assert 'main.tex' in file_issues
    assert file_issues['main.tex'][0]['severity'] == 'danger'


# --- preflight status "error" -----------------------------------------------------

def _pf_error(info="QA check failed: exe-in-submission"):
    """Payload the producer returns when the scan is aborted: no files at all."""
    return {"status": {"key": "error", "info": info},
            "detected_toplevel_files": [], "tex_files": []}


def test_preflight_error_status_blocks():
    assert has_blocking_issues(_pf_error()) is True
    # Selection-aware downgrading never applies: the error has no file.
    assert has_blocking_issues(_pf_error(), {"main.tex"}) is True


def test_preflight_error_status_shows_reason():
    notes, file_issues = build_issue_context(_pf_error())
    assert len(notes) == 1
    assert notes[0]["severity"] == "danger"
    assert "exe-in-submission" in notes[0]["body"]
    assert file_issues == {}


def test_preflight_error_reason_can_be_hidden(monkeypatch):
    # POLICY switch SHOW_PREFLIGHT_ERROR_DETAIL: still blocks, no reason text.
    monkeypatch.setitem(PREFLIGHT_ISSUE_DIRECTIVES["preflight_error"],
                        "show_info", False)
    notes, _ = build_issue_context(_pf_error())
    assert notes[0]["severity"] == "danger"
    assert "exe-in-submission" not in notes[0]["body"]


def test_success_status_adds_nothing():
    pf = _pf()
    pf["status"] = {"key": "success", "info": None}
    assert build_issue_context(pf) == ([], {})


# --- POLICY: unlisted codes and status "suspicious" are hidden from submitters ----

def test_unlisted_code_is_hidden_and_does_not_block():
    pf = _pf("some_plugin_defined_code")
    assert build_issue_context(pf) == ([], {})
    assert has_blocking_issues(pf) is False


def test_unlisted_code_shown_as_warning_when_switched_on(monkeypatch):
    # POLICY switch SHOW_UNLISTED_CODES=True: the previous behaviour.
    # Flipping the switch rebinds DEFAULT_DIRECTIVE at import time; both modules
    # hold that object, so patch both names here.
    from submit_ce.ui.preflight import issue_table, issues
    shown = {"severity": "warning", "message": None}
    monkeypatch.setattr(issue_table, "DEFAULT_DIRECTIVE", shown)
    monkeypatch.setattr(issues, "DEFAULT_DIRECTIVE", shown)
    notes, file_issues = build_issue_context(_pf("some_plugin_defined_code"))
    assert [n["severity"] for n in notes] == ["warning"]
    assert file_issues["main.tex"][0]["severity"] == "warning"


def test_suspicious_status_is_hidden():
    pf = _pf()
    pf["status"] = {"key": "suspicious", "info": None}
    assert build_issue_context(pf) == ([], {})
    assert has_blocking_issues(pf) is False


def test_moderator_findings_lists_unlisted_codes_and_suspicious():
    from submit_ce.ui.preflight.issues import moderator_findings
    pf = _pf("some_plugin_defined_code", "file_not_found",
             "some_plugin_defined_code")
    pf["status"] = {"key": "suspicious", "info": None}
    assert moderator_findings(pf) == ["some_plugin_defined_code",
                                      "preflight_suspicious"]
    assert moderator_findings(_pf("file_not_found")) == []
    assert moderator_findings(None) == []
