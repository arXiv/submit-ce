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
               for k in ("badges", "is_readme", "is_toplevel", "is_used",
                         "is_unused", "is_protected"))


def test_usage_classification_by_confidence():
    """is_used / is_maybe_used / is_unused are mutually exclusive; a resolved
    edge beats the maybe-used flag; readme + top-level are none of them but are
    protected. (SUBMISSION-221 / C3.2a)"""
    notes = [
        {"filename": "00README.json"},
        {"filename": "main.tex"},                                    # top-level
        {"filename": "fig.png", "used_by": ["main.tex"]},             # used
        {"filename": "guess.sty", "is_maybe_used": True},             # maybe-used
        {"filename": "orphan.dat"},                                   # unused
        {"filename": "both.sty", "used_by_tex": ["main.tex"],         # edge wins
         "is_maybe_used": True},
    ]
    by = {r["filename"]: r for r in build_file_rows(notes, {}, ["main.tex"])}

    assert (by["fig.png"]["is_used"], by["fig.png"]["is_protected"]) == (True, True)
    assert by["guess.sty"]["is_maybe_used"] is True
    assert by["guess.sty"]["is_unused"] is False
    assert by["guess.sty"]["is_protected"] is False          # deletable
    assert by["orphan.dat"]["is_unused"] is True
    assert by["orphan.dat"]["is_protected"] is False          # deletable
    # resolved edge beats the maybe-used flag
    assert by["both.sty"]["is_used"] is True
    assert by["both.sty"]["is_maybe_used"] is False
    # readme + top-level are protected but not used/maybe/unused
    for f in ("00README.json", "main.tex"):
        assert by[f]["is_protected"] is True
        assert not (by[f]["is_used"] or by[f]["is_maybe_used"]
                    or by[f]["is_unused"])


def test_is_unused_only_for_unreferenced_ordinary_files():
    """"Not used" = an ordinary file nothing references. The 00README, the
    selected top-level, and any referenced file are all 'used'. (SUBMISSION-220)"""
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


def test_used_is_rooted_at_selection_when_used_filenames_given():
    """With `used_filenames` (the rooted reachable set), a file's used/unused
    note follows the current top-level selection, not a flat union of every
    reference (SUBMISSION-231). Same files, two selections, opposite results."""
    notes = [
        {"filename": "main1.tex"},
        {"filename": "main2.tex"},
        {"filename": "only1.png", "used_by": ["main1.tex"]},
        {"filename": "only2.png", "used_by": ["main2.tex"]},
    ]
    # main1 selected: reachable set is {only1.png}
    by1 = {r["filename"]: r for r in
           build_file_rows(notes, {}, ["main1.tex"], {"only1.png"})}
    assert by1["only1.png"]["is_used"] and by1["only1.png"]["is_protected"]
    assert by1["only2.png"]["is_unused"] and not by1["only2.png"]["is_protected"]

    # main2 selected: the very same only2.png flips to used/protected.
    by2 = {r["filename"]: r for r in
           build_file_rows(notes, {}, ["main2.tex"], {"only2.png"})}
    assert by2["only2.png"]["is_used"] and by2["only2.png"]["is_protected"]
    assert by2["only1.png"]["is_unused"] and not by2["only1.png"]["is_protected"]


def test_unselected_toplevel_candidate_not_auto_checked():
    """A detected top-level the submitter hasn't selected must NOT be auto-checked
    for deletion (is_unused cleared), while a plain unused file still is. Protects
    the no-JS path (SUBMISSION-244). Both remain deletable (not protected)."""
    notes = [
        {"filename": "main1.tex"},   # selected top-level
        {"filename": "main2.tex"},   # detected candidate, NOT selected
        {"filename": "orphan.png"},  # plain unused, not a candidate
    ]
    by = {r["filename"]: r for r in build_file_rows(
        notes, {}, ["main1.tex"],
        used_filenames=set(),                       # nothing reachable
        toplevel_candidates={"main1.tex", "main2.tex"},
    )}

    # Selected top-level: handled as top-level, not unused.
    assert by["main1.tex"]["is_toplevel"] and not by["main1.tex"]["is_unused"]
    # Unselected candidate: "Not used" but NOT auto-checked (is_unused cleared),
    # and still deletable (not protected).
    assert by["main2.tex"]["is_unused"] is False
    assert by["main2.tex"]["is_protected"] is False
    # Plain unused non-candidate: auto-checked as usual.
    assert by["orphan.png"]["is_unused"] is True


def test_toplevel_candidates_omitted_keeps_auto_check():
    """Without toplevel_candidates (older callers), an unreferenced file is still
    is_unused -- the pre-244 behavior is unchanged."""
    notes = [{"filename": "main1.tex"}, {"filename": "main2.tex"}]
    by = {r["filename"]: r for r in build_file_rows(
        notes, {}, ["main1.tex"], used_filenames=set())}
    assert by["main2.tex"]["is_unused"] is True


def test_unanalyzed_file_labeled_not_auto_checked():
    """A stored file preflight never analyzed (is_unanalyzed) renders "Not
    analyzed": not is_used/maybe/unused, not auto-checked, still deletable
    (SUBMISSION-246). The 00README guard still wins over is_unanalyzed."""
    notes = [
        {"filename": "main.tex"},                        # top-level
        {"filename": "stray.txt", "is_unanalyzed": True},  # bucket-only
        {"filename": "00README.json", "is_unanalyzed": True},  # readme wins
    ]
    by = {r["filename"]: r for r in build_file_rows(
        notes, {}, ["main.tex"], used_filenames=set())}

    s = by["stray.txt"]
    assert s["is_unanalyzed"] is True
    assert not (s["is_used"] or s["is_maybe_used"] or s["is_unused"])
    assert s["is_protected"] is False        # deletable, but template leaves it unchecked
    # readme classification takes precedence over is_unanalyzed
    assert by["00README.json"]["is_readme"] is True
    assert by["00README.json"]["is_unanalyzed"] is False


def test_empty_used_filenames_marks_all_ordinary_unused():
    """An empty rooted set (e.g. no top-level yet selected, or nothing reachable)
    is distinct from None: every ordinary file is 'not used' even if it carries
    reverse-edge data."""
    notes = [
        {"filename": "main.tex"},
        {"filename": "fig.png", "used_by": ["main.tex"]},
    ]
    by = {r["filename"]: r for r in build_file_rows(notes, {}, ["main.tex"], set())}
    assert by["fig.png"]["is_unused"] and not by["fig.png"]["is_used"]


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
