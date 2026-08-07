"""Tests for :mod:`submit_ce.ui.preflight.file_context`. [SUBMISSION-219 / F0]"""

from submit_ce.ui.preflight.file_context import build_file_rows


def _notes():
    return [
        {"filename": "00README.json"},
        {"filename": "main.tex"},
        {"filename": "refs.bib", "used_by_bib": ["main.tex"]},
    ]


def test_flags_readme_and_toplevel():
    rows = build_file_rows(_notes(), {}, ["main.tex"])
    by_name = {r["filename"]: r for r in rows}
    assert by_name["00README.json"]["is_readme"] is True
    assert by_name["00README.json"]["is_toplevel"] is False
    assert by_name["main.tex"]["is_toplevel"] is True
    assert by_name["main.tex"]["is_readme"] is False
    assert by_name["refs.bib"]["is_readme"] is False
    assert by_name["refs.bib"]["is_toplevel"] is False


def test_badges_default_to_empty_list_and_attach_by_filename():
    issues = {"main.tex": [{"severity": "danger", "label": "conflicting file type"}]}
    rows = build_file_rows(_notes(), issues, [])
    by_name = {r["filename"]: r for r in rows}
    assert by_name["main.tex"]["badges"] == [
        {"severity": "danger", "label": "conflicting file type"}]
    # Files with no issue get an empty list, never None, so the template can
    # test truthiness uniformly.
    assert by_name["refs.bib"]["badges"] == []
    assert by_name["00README.json"]["badges"] == []


def test_preflight_keys_are_preserved():
    rows = build_file_rows(_notes(), {}, [])
    refs = next(r for r in rows if r["filename"] == "refs.bib")
    assert refs["used_by_bib"] == ["main.tex"]


def test_input_dicts_are_not_mutated():
    notes = _notes()
    build_file_rows(notes, {"main.tex": [{"severity": "danger", "label": "x"}]},
                    ["main.tex"])
    # Original notes must be untouched (no badges/is_readme/is_toplevel leaked in).
    assert all("badges" not in n and "is_readme" not in n
               and "is_toplevel" not in n for n in notes)


def test_none_issues_and_none_selection_are_safe():
    rows = build_file_rows(_notes(), None, None)
    assert all(r["badges"] == [] and r["is_toplevel"] is False for r in rows)


def test_empty_notes_returns_empty():
    assert build_file_rows([], {}, ["main.tex"]) == []
