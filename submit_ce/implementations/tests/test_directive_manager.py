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
    preflight = {
        "detected_toplevel_files": [{"filename": "main.tex"}],
        "tex_files": [{"filename": "main.tex"}, {"filename": "extra.tex"}],
        "ancillary_files": [{"filename": "anc.dat"}],
        "maybe_used_files": [{"filename": "maybe.txt"}],
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


def test_get_files_from_preflight_empty():
    assert dm.get_files_from_preflight({}) == []


def test_get_files_from_preflight_with_testdata():
    preflight = json.loads((_TESTDATA / "gcp_preflight.json").read_text())
    result = dm.get_files_from_preflight(preflight)
    filenames = [f["filename"] for f in result]
    assert "main-test1.tex" in filenames
