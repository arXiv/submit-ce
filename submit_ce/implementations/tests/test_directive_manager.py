import json
from pathlib import Path

from submit_ce.implementations.compile.directive_manager import DirectiveManager

_TESTDATA = Path(__file__).parents[3] / "testdata" / "1"


def test_convert_preflight_to_directives():
    preflight_text = (_TESTDATA / "gcp_preflight.json").read_text()
    expected = json.loads((_TESTDATA / "src" / "00README.json").read_text())

    result = DirectiveManager().convert_preflight_to_directives(preflight_text)

    assert result["sources"][0]["filename"] == expected["sources"][0]["filename"]
