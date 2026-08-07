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
    # Original notes must be untouched (no derived keys leaked in).
    assert all(k not in n for n in notes
               for k in ("badges", "is_readme", "is_toplevel", "is_unused"))


def test_is_unused_only_for_unreferenced_ordinary_files():
    """"Not used" = an ordinary file nothing references. The 00README, the
    selected top-level, and any referenced file are all 'used'. (SUBMISSION-220
    / C3.1a)"""
    notes = [
        {"filename": "00README.json"},
        {"filename": "main.tex"},                              # selected top-level
        {"filename": "refs.bib", "used_by_bib": ["main.tex"]},  # referenced
        {"filename": "sec.tex", "used_by_tex": ["main.tex"]},   # referenced
        {"filename": "fig.png", "used_by": ["main.tex"]},       # referenced
        {"filename": "orphan.png"},                             # nothing references
    ]
    by_name = {r["filename"]: r for r in build_file_rows(notes, {}, ["main.tex"])}
    assert by_name["orphan.png"]["is_unused"] is True
    assert by_name["00README.json"]["is_unused"] is False
    assert by_name["main.tex"]["is_unused"] is False
    assert by_name["refs.bib"]["is_unused"] is False
    assert by_name["sec.tex"]["is_unused"] is False
    assert by_name["fig.png"]["is_unused"] is False


def test_none_issues_and_none_selection_are_safe():
    rows = build_file_rows(_notes(), None, None)
    assert all(r["badges"] == [] and r["is_toplevel"] is False for r in rows)


def test_empty_notes_returns_empty():
    assert build_file_rows([], {}, ["main.tex"]) == []


def test_image_size_fields_pass_through_unchanged():
    """Extra per-file keys (e.g. the image size fields get_files_from_preflight
    attaches) flow through to the row without special handling -- the point of
    the single per-file object (SUBMISSION-172)."""
    notes = [{"filename": "big.png", "width": 7000, "height": 7000,
              "megapixels": 49.0, "file_bytes": 12_000_000, "is_oversized": True}]
    row = build_file_rows(notes, {}, [])[0]
    assert row["megapixels"] == 49.0
    assert row["width"] == 7000
    assert row["is_oversized"] is True
    assert row["file_bytes"] == 12_000_000
