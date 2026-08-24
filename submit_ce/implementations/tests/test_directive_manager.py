import json
from pathlib import Path

from submit_ce.implementations.compile.directive_manager import DirectiveManager as dm

_TESTDATA = Path(__file__).parents[3] / "testdata" / "1"


def test_convert_zzrm_to_user_decisions():
    zzrm = json.loads((_TESTDATA / "src" / "00README.json").read_text())
    user_decisions = json.loads((_TESTDATA / "user_decisions.json").read_text())
    result = dm.convert_zzrm_to_user_decisions(zzrm)

    assert result["sources"][0]["filename"] == user_decisions["sources"][0]["filename"]


def test_convert_zzrm_to_user_decisions_empty():
    assert dm.convert_zzrm_to_user_decisions({}) == {}


def test_convert_zzrm_to_user_decisions_keeps_only_filename():
    zzrm = {"sources": [{"filename": "main.tex", "usage": "toplevel", "ignored": "x"}]}
    result = dm.convert_zzrm_to_user_decisions(zzrm)
    assert result["sources"] == [{"filename": "main.tex"}]


def test_convert_zzrm_to_user_decisions_preserves_texlive_version():
    zzrm = {"texlive_version": "2025"}
    assert dm.convert_zzrm_to_user_decisions(zzrm) == {"texlive_version": "2025"}


def test_convert_zzrm_to_user_decisions_keeps_only_toplevel_sources():
    zzrm = {
        "sources": [
            {"filename": "main.tex", "usage": "toplevel"},
            {"filename": "old.tex", "usage": "ignore"},
            {"filename": "fig.pdf", "usage": "include"},
        ],
    }
    result = dm.convert_zzrm_to_user_decisions(zzrm)
    assert result["sources"] == [{"filename": "main.tex"}]


def test_convert_zzrm_to_user_decisions_drops_process_compiler_version():
    zzrm = {
        "sources": [{"filename": "main.tex", "usage": "toplevel"}],
        "texlive_version": "2025",
        "process": {"compiler": "pdflatex", "compiler_version": "2025"},
    }
    result = dm.convert_zzrm_to_user_decisions(zzrm)
    assert result["process"] == {"compiler": "pdflatex"}


def test_get_files_from_preflight_collects_all_sections():
    # NB: PreflightResponse types ancillary_files and maybe_used_files as
    # list[str] -- plain filenames, not dicts (SUBMISSION-221 fix).
    preflight = {
        "detected_toplevel_files": [{"filename": "main.tex"}],
        "tex_files": [{"filename": "main.tex"}, {"filename": "extra.tex"}],
        "ancillary_files": ["anc.dat"],
        "maybe_used_files": ["maybe.txt"],
        "image_files": [{"filename": "fig.pdf"}],
    }
    result = dm.get_files_from_preflight(preflight)
    filenames = {f["filename"] for f in result}
    assert filenames == {"main.tex", "extra.tex", "anc.dat", "maybe.txt", "fig.pdf"}


def test_get_files_from_preflight_builds_used_by_refs():
    preflight = {
        "tex_files": [
            {
                "filename": "main.tex",
                "used_other_files": ["fig.pdf"],
                "used_tex_files": ["sec.tex"],
                "used_bib_files": ["refs.bib"],
            }
        ]
    }
    by_name = {f["filename"]: f for f in dm.get_files_from_preflight(preflight)}
    assert by_name["fig.pdf"]["used_by"] == ["main.tex"]
    assert by_name["sec.tex"]["used_by_tex"] == ["main.tex"]
    assert by_name["refs.bib"]["used_by_bib"] == ["main.tex"]


def test_get_files_from_preflight_carries_image_size_fields():
    """Image size metadata rides through onto the file row (SUBMISSION-172). is_oversized is taken verbatim from preflight -- it already encodes
    "large AND not fast-copy" -- so a large fast-copy image is NOT oversized
    while a same-size slow-copy image is."""
    preflight = {
        "image_files": [
            {"filename": "big_slow.png", "width": 7000, "height": 7000,
             "megapixels": 49.0, "file_bytes": 12_000_000,
             "is_oversized": True, "pdftex-fast-copy": False},
            {"filename": "big_fast.png", "width": 7000, "height": 7000,
             "megapixels": 49.0, "file_bytes": 4_000_000,
             "is_oversized": False, "pdftex-fast-copy": True},
            {"filename": "small.png", "width": 1000, "height": 1000,
             "megapixels": 1.0, "file_bytes": 200_000,
             "is_oversized": False, "pdftex-fast-copy": True},
        ],
    }
    by_name = {f["filename"]: f for f in dm.get_files_from_preflight(preflight)}

    assert by_name["big_slow.png"]["megapixels"] == 49.0
    assert by_name["big_slow.png"]["width"] == 7000
    assert by_name["big_slow.png"]["height"] == 7000
    assert by_name["big_slow.png"]["file_bytes"] == 12_000_000
    assert by_name["big_slow.png"]["is_oversized"] is True
    # Same pixel count, but fast-copy -> not oversized.
    assert by_name["big_fast.png"]["is_oversized"] is False
    assert by_name["small.png"]["is_oversized"] is False


def test_get_files_from_preflight_image_without_oversized_defaults_false():
    preflight = {"image_files": [{"filename": "fig.png", "megapixels": 2.0}]}
    row = dm.get_files_from_preflight(preflight)[0]
    assert row["is_oversized"] is False


def test_used_source_filenames_unions_resolved_edges():
    """The confidently-used set = union of every tex file's resolved edges
    (SUBMISSION-221 / C3.2a)."""
    preflight = {"tex_files": [
        {"filename": "main.tex", "used_other_files": ["fig.png"],
         "used_bib_files": ["refs.bib"]},
        {"filename": "sec.tex", "used_tex_files": ["sub.tex"]},
    ]}
    assert dm.used_source_filenames(preflight) == {"fig.png", "refs.bib", "sub.tex"}
    assert dm.used_source_filenames({}) == set()


# --- reachable_from: rooted reachability (SUBMISSION-231) -------------------

_TWO_TOP_LEVELS = {"tex_files": [
    {"filename": "main1.tex", "used_tex_files": ["chap1.tex"],
     "used_other_files": ["shared.png"]},
    {"filename": "chap1.tex", "used_other_files": ["fig1.png"]},
    {"filename": "main2.tex", "used_tex_files": ["chap2.tex"],
     "used_bib_files": ["refs.bib"]},
    {"filename": "chap2.tex", "used_other_files": ["fig2.png"]},
]}


def test_reachable_from_is_rooted_at_selection():
    """Only files reachable from the selected top-level count as used, and the
    traversal is transitive (main1 -> chap1 -> fig1)."""
    assert dm.reachable_from(["main1.tex"], _TWO_TOP_LEVELS) == {
        "chap1.tex", "fig1.png", "shared.png"}
    assert dm.reachable_from(["main2.tex"], _TWO_TOP_LEVELS) == {
        "chap2.tex", "fig2.png", "refs.bib"}


def test_reachable_from_multiple_roots_is_union():
    both = dm.reachable_from(["main1.tex", "main2.tex"], _TWO_TOP_LEVELS)
    assert both == (dm.reachable_from(["main1.tex"], _TWO_TOP_LEVELS)
                    | dm.reachable_from(["main2.tex"], _TWO_TOP_LEVELS))


def test_reachable_from_excludes_roots_and_handles_cycles():
    # a <-> b cycle plus a self-reference must terminate and not include roots.
    preflight = {"tex_files": [
        {"filename": "a.tex", "used_tex_files": ["b.tex", "a.tex"]},
        {"filename": "b.tex", "used_tex_files": ["a.tex"], "used_other_files": ["c.png"]},
    ]}
    assert dm.reachable_from(["a.tex"], preflight) == {"b.tex", "c.png"}


def test_reachable_from_empty_roots_or_data():
    assert dm.reachable_from([], _TWO_TOP_LEVELS) == set()
    assert dm.reachable_from(["main1.tex"], {}) == set()
    assert dm.reachable_from(None, None) == set()


def test_used_edges_flattens_resolved_references():
    """used_edges is the adjacency the client walk and reachable_from share:
    {tex filename: [all referenced filenames]} (SUBMISSION-231)."""
    edges = dm.used_edges(_TWO_TOP_LEVELS)
    assert edges["main1.tex"] == ["chap1.tex", "shared.png"]
    assert edges["chap1.tex"] == ["fig1.png"]
    assert edges["main2.tex"] == ["chap2.tex", "refs.bib"]
    assert dm.used_edges({}) == {}


def test_reachable_from_uses_used_edges_graph():
    """reachable_from is a BFS over exactly the used_edges adjacency."""
    edges = dm.used_edges(_TWO_TOP_LEVELS)
    # Everything reachable from main1 is a node/target present in the graph.
    reach = dm.reachable_from(["main1.tex"], _TWO_TOP_LEVELS)
    assert reach == {"chap1.tex", "shared.png", "fig1.png"}
    assert set(edges["main1.tex"]) <= reach


def test_files_for_review_is_bucket_authoritative():
    """The Review file list comes from the STORED files (bucket), annotated with
    preflight info. A stored file preflight never mentioned is tagged
    is_unanalyzed; a preflight-referenced file NOT stored is dropped
    (SUBMISSION-246)."""
    preflight = {"tex_files": [
        {"filename": "main.tex", "used_other_files": ["fig.png", "missing.png"]},
    ]}
    # Bucket has main.tex, fig.png, and a stray file preflight never analyzed.
    # "missing.png" is referenced by preflight but NOT in the bucket.
    stored = ["main.tex", "fig.png", "stray.txt"]
    rows = {r["filename"]: r for r in dm.files_for_review(stored, preflight)}

    assert set(rows) == {"main.tex", "fig.png", "stray.txt"}   # bucket, not preflight
    assert "missing.png" not in rows                            # phantom ref dropped
    assert rows["fig.png"].get("used_by") == ["main.tex"]       # annotation carried
    assert not rows["fig.png"].get("is_unanalyzed")
    assert rows["stray.txt"].get("is_unanalyzed") is True       # no preflight entry


def test_files_for_review_d1_regression_unsupported_readme():
    """D1: preflight omits files it can't analyze (e.g. an unsupported 00README
    format), so a report-sourced list under-counts. Bucket-sourced list shows
    all three; the offending 00README.yaml is visible (SUBMISSION-246)."""
    preflight = {"tex_files": [{"filename": "main.tex"}]}   # only main.tex analyzed
    stored = ["main.tex", "00README.yaml", "notes.txt"]
    rows = {r["filename"]: r for r in dm.files_for_review(stored, preflight)}
    assert set(rows) == {"main.tex", "00README.yaml", "notes.txt"}
    assert rows["00README.yaml"]["is_unanalyzed"] is True
    assert rows["notes.txt"]["is_unanalyzed"] is True


def test_get_files_from_preflight_tags_maybe_used():
    """Files from the maybe_used_files section are tagged is_maybe_used so the UI
    can tell them apart from truly-unused files (SUBMISSION-221 / C3.2a)."""
    preflight = {"maybe_used_files": ["guess.sty"], "tex_files": []}
    row = dm.get_files_from_preflight(preflight)[0]
    assert row["filename"] == "guess.sty"
    assert row["is_maybe_used"] is True


def test_get_files_from_preflight_empty():
    assert dm.get_files_from_preflight({}) == []


def test_get_files_from_preflight_with_testdata():
    preflight = json.loads((_TESTDATA / "gcp_preflight.json").read_text())
    result = dm.get_files_from_preflight(preflight)
    filenames = [f["filename"] for f in result]
    assert "main-test1.tex" in filenames


def test_get_lang_from_preflight_with_testdata():
    preflight = json.loads((_TESTDATA / "gcp_preflight.json").read_text())
    assert dm.get_lang_from_preflight(preflight) == "tex"
