import json
import pytest

from submit_ce.implementations.compile.directive_manager import DirectiveManager


@pytest.fixture
def manager():
    return DirectiveManager()


def preflight_json(toplevel_files=None, **kwargs):
    data = {"detected_toplevel_files": toplevel_files or [], **kwargs}
    return json.dumps(data)


def toplevel(filename, engine="tex", lang="latex", output="pdf", postp="none", fontmaps=None):
    compiler = {"engine": engine, "lang": lang, "output": output, "postp": postp}
    process = {"compiler": compiler}
    if fontmaps:
        process["fontmaps"] = fontmaps
    return {"filename": filename, "process": process}


# --- compiler selection ---

def test_pdflatex(manager):
    result = manager.convert_preflight_to_directives(
        preflight_json([toplevel("main.tex")])
    )
    assert result["process"]["compiler"] == "pdflatex"


def test_lualatex(manager):
    result = manager.convert_preflight_to_directives(
        preflight_json([toplevel("main.tex", engine="luatex")])
    )
    assert result["process"]["compiler"] == "lualatex"


def test_xelatex(manager):
    result = manager.convert_preflight_to_directives(
        preflight_json([toplevel("main.tex", engine="xetex")])
    )
    assert result["process"]["compiler"] == "xelatex"


def test_latex_dvi(manager):
    result = manager.convert_preflight_to_directives(
        preflight_json([toplevel("main.tex", output="dvi")])
    )
    assert result["process"]["compiler"] == "latex"


def test_pdftex(manager):
    result = manager.convert_preflight_to_directives(
        preflight_json([toplevel("main.tex", lang="tex", output="pdf", engine="tex")])
    )
    assert result["process"]["compiler"] == "pdftex"


def test_pdf_submission(manager):
    result = manager.convert_preflight_to_directives(
        preflight_json([toplevel("paper.pdf", lang="pdf", engine="unknown", output="unknown")])
    )
    assert result["process"]["compiler"] == "pdf"


def test_html_submission(manager):
    result = manager.convert_preflight_to_directives(
        preflight_json([toplevel("index.html", lang="html", engine="unknown", output="unknown")])
    )
    assert result["process"]["compiler"] == "html"


def test_postp_appended(manager):
    result = manager.convert_preflight_to_directives(
        preflight_json([toplevel("main.tex", output="dvi", postp="dvips_ps2pdf")])
    )
    assert result["process"]["compiler"] == "latex+dvips_ps2pdf"


def test_postp_none_not_appended(manager):
    result = manager.convert_preflight_to_directives(
        preflight_json([toplevel("main.tex", postp="none")])
    )
    assert "+" not in result["process"]["compiler"]


# --- sources ---

def test_single_toplevel_source(manager):
    result = manager.convert_preflight_to_directives(
        preflight_json([toplevel("main.tex")])
    )
    assert result["sources"] == [{"filename": "main.tex", "usage": "toplevel"}]


def test_multiple_toplevel_sources(manager):
    result = manager.convert_preflight_to_directives(
        preflight_json([toplevel("a.tex"), toplevel("b.tex")])
    )
    assert result["sources"] == [
        {"filename": "a.tex", "usage": "toplevel"},
        {"filename": "b.tex", "usage": "toplevel"},
    ]


def test_compiler_from_first_toplevel(manager):
    # second file has luatex but compiler should come from first
    result = manager.convert_preflight_to_directives(
        preflight_json([toplevel("a.tex", engine="tex"), toplevel("b.tex", engine="luatex")])
    )
    assert result["process"]["compiler"] == "pdflatex"


# --- fontmaps ---

def test_fontmaps_included(manager):
    result = manager.convert_preflight_to_directives(
        preflight_json([toplevel("main.tex", fontmaps=["mymap.map"])])
    )
    assert result["process"]["fontmaps"] == ["mymap.map"]


def test_fontmaps_absent_when_none(manager):
    result = manager.convert_preflight_to_directives(
        preflight_json([toplevel("main.tex")])
    )
    assert "fontmaps" not in result["process"]


# --- empty / missing toplevel files ---

def test_no_toplevel_files_defaults_pdflatex(manager):
    result = manager.convert_preflight_to_directives(preflight_json([]))
    assert result["process"]["compiler"] == "pdflatex"
    assert "sources" not in result


def test_missing_compiler_field_defaults(manager):
    data = {"detected_toplevel_files": [{"filename": "main.tex", "process": {}}]}
    result = manager.convert_preflight_to_directives(json.dumps(data))
    assert result["process"]["compiler"] == "pdflatex"
    assert result["sources"] == [{"filename": "main.tex", "usage": "toplevel"}]


def test_unknown_compiler_combo_defaults(manager):
    result = manager.convert_preflight_to_directives(
        preflight_json([toplevel("main.tex", lang="unknown", engine="unknown", output="unknown")])
    )
    assert result["process"]["compiler"] == "pdflatex"


# --- spec_version ---

def test_spec_version(manager):
    result = manager.convert_preflight_to_directives(preflight_json([toplevel("main.tex")]))
    assert result["spec_version"] == 1


