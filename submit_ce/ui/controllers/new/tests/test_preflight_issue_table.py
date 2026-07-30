"""Structural checks for the preflight issue / severity / message table.

[SUBMISSION-211] These validate the table's shape, not the extraction logic
(that lives with ``build_issue_context`` and is tested separately). The point is
to catch drift while the team reviews severities and copy.
"""
from submit_ce.ui.controllers.new.preflight_issue_table import (
    DEFAULT_DIRECTIVE,
    PREFLIGHT_ISSUE_DIRECTIVES,
    SEVERITY_RANK,
    SILENT,
    directive_for,
)

VISIBLE_SEVERITIES = {"danger", "warning", "info"}
ALL_SEVERITIES = VISIBLE_SEVERITIES | {SILENT}


def test_every_entry_has_a_known_severity():
    for code, directive in PREFLIGHT_ISSUE_DIRECTIVES.items():
        assert directive.get("severity") in ALL_SEVERITIES, code


def test_visible_entries_have_a_message_and_silent_ones_do_not():
    for code, directive in PREFLIGHT_ISSUE_DIRECTIVES.items():
        if directive["severity"] == SILENT:
            assert "message" not in directive, f"{code}: silent entries carry no copy"
        else:
            assert directive.get("message"), f"{code}: visible entries need a message"


def test_links_are_paired():
    # A url is only useful with link text, and link text without a url is dead.
    for code, directive in PREFLIGHT_ISSUE_DIRECTIVES.items():
        assert bool(directive.get("url")) == bool(directive.get("link_text")), code


def test_count_placeholder_is_well_formed():
    # {n} is the only template token; substituting it must leave no stray {n}.
    for code, directive in PREFLIGHT_ISSUE_DIRECTIVES.items():
        msg = directive.get("message")
        if msg:
            assert "{n}" not in msg.replace("{n}", ""), code


def test_severity_rank_covers_visible_severities():
    assert VISIBLE_SEVERITIES <= set(SEVERITY_RANK)


def test_directive_for_unknown_code_returns_default():
    assert directive_for("definitely_not_a_real_code") is DEFAULT_DIRECTIVE


def test_directive_for_known_code_returns_entry():
    assert directive_for("file_not_found") is PREFLIGHT_ISSUE_DIRECTIVES["file_not_found"]


def test_decided_severities():
    # Guardrails for decisions already made; update deliberately if they change.
    assert PREFLIGHT_ISSUE_DIRECTIVES["no_top_level_file"]["severity"] == "danger"
    assert PREFLIGHT_ISSUE_DIRECTIVES["conflicting_file_type"]["severity"] == "danger"
    assert PREFLIGHT_ISSUE_DIRECTIVES["file_not_found"]["severity"] == "warning"
    assert PREFLIGHT_ISSUE_DIRECTIVES["issue_in_subfile"]["severity"] == SILENT
