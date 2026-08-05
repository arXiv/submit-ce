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


def test_hyperref_not_found_is_derived_from_boolean():
    """hyperref_not_found is no longer an emitted issue; it's derived from
    ToplevelFile.hyperref_found == False."""
    preflight = {
        'detected_toplevel_files': [
            {'filename': 'main.tex', 'hyperref_found': False, 'issues': []},
        ],
    }
    notifications, _ = build_issue_context(preflight)
    titles = [n['title'] for n in notifications]
    assert any('hyperref' in t for t in titles)
    assert notifications[0]['severity'] == 'info'


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
