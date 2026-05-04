import json
import sys
from collections import OrderedDict

'''
This version is paused.
This looks like a lot less code than directive_manager2,
which has code to read local files, support yaml, etc.


The review files page allows the user to do 3 things:
- select compiler
- select main source file
- delete files not needed or accidentally included, etc.

In legacy, submit makes an external call to submission-tools.
If we continue that design decision os separation, 
then pdf2tex development will not require changes to submission.

So the approach here is to limit what submit-ce needs to know
about compiling tex, and only focus on storing user selections.

TODO: also parse files
'''


# Maps (lang, output, engine) -> compiler string, mirroring preflight CompilerSpec._COMPILER_SELECTION
_COMPILER_SELECTION: dict[tuple[str, str, str], str] = {
    ("latex", "pdf",  "tex"):    "pdflatex",
    ("latex", "pdf",  "luatex"): "lualatex",
    ("latex", "pdf",  "xetex"):  "xelatex",
    ("latex", "dvi",  "tex"):    "latex",
    ("latex", "dvi",  "luatex"): "dvilualatex",
    ("latex", "dvi",  "ptex"):   "platex",
    ("latex", "dvi",  "uptex"):  "uplatex",
    ("tex",   "pdf",  "tex"):    "pdftex",   # pdfetex alias
    ("tex",   "pdf",  "luatex"): "luatex",
    ("tex",   "pdf",  "xetex"):  "xetex",
    ("tex",   "dvi",  "tex"):    "etex",
    ("tex",   "dvi",  "luatex"): "dviluatex",
    ("tex",   "dvi",  "ptex"):   "ptex",
    ("tex",   "dvi",  "uptex"):  "uptex",
}

_DEFAULT_COMPILER = "pdflatex"
_ZZRM_SPEC_VERSION = 1


def _compiler_string(compiler: dict) -> str:
    lang = compiler.get("lang", "unknown")
    if lang == "pdf":
        return "pdf"
    if lang == "html":
        return "html"
    engine = compiler.get("engine", "unknown")
    output = compiler.get("output", "unknown")
    postp = compiler.get("postp")
    result = _COMPILER_SELECTION.get((lang, output, engine), _DEFAULT_COMPILER)
    if postp and postp not in ("none", "unknown"):
        result += f"+{postp}"
    return result


class DirectiveManager:

    def convert_preflight_to_directives(self, content: str) -> dict:
        preflight = json.loads(content)
        toplevel_files = preflight.get("detected_toplevel_files", [])

        compiler_str = _DEFAULT_COMPILER
        if toplevel_files:
            first_process = toplevel_files[0].get("process", {})
            compiler = first_process.get("compiler")
            if compiler:
                compiler_str = _compiler_string(compiler)

        result: OrderedDict = OrderedDict()
        result["process"] = {"compiler": compiler_str}

        fontmaps = toplevel_files[0].get("process", {}).get("fontmaps") if toplevel_files else None
        if fontmaps:
            result["process"]["fontmaps"] = fontmaps

        if toplevel_files:
            result["sources"] = [{"filename": tlf["filename"], "usage": "toplevel"} for tlf in toplevel_files]

        result["spec_version"] = _ZZRM_SPEC_VERSION
        return result


# ie: python submit_ce/implementations/compile/directive_manager.py testdata/new/.../gcp_preflight.json
if __name__ == "__main__":
    content = open(sys.argv[1]).read()
    print(json.dumps(DirectiveManager().convert_preflight_to_directives(content), indent=2))
