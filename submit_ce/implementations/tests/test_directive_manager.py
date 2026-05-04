import json
from pathlib import Path

from submit_ce.implementations.compile.directive_manager import DirectiveManager

_TESTDATA = Path(__file__).parents[3] / "testdata" / "new" / "7522" / "7522484"


def test_convert_preflight_to_directives():
    preflight_text = (_TESTDATA / "gcp_preflight.json").read_text()
    expected = json.loads((_TESTDATA / "src" / "00README.json").read_text())

    result = DirectiveManager().convert_preflight_to_directives(preflight_text)

    # 00README.json may contain extra fields (e.g. texlive_version) added later;
    # check only the keys that convert_preflight_to_directives produces.
    for key, value in result.items():
        assert value == expected[key], f"Mismatch for key '{key}': {value!r} != {expected[key]!r}"
