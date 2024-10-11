import json

from hypothesis import given, strategies, settings
from hypothesis_jsonschema import from_schema
from pydantic import TypeAdapter, RootModel

from submit_ce.api.domain import Submission


def test_roundtrip_submission_to_json():
    """Tests if Submission can be round tripped to json."""
    schema = TypeAdapter(Submission).json_schema()

    @given(from_schema(schema))
    @settings(max_examples=3)
    def do_submission_round_trip(klass, first_dict): # has klass to make display by given look reasonable
        print(f"class: {klass} example instance: {first_dict}")
        first_instance = TypeAdapter(klass).validate_json(json.dumps(first_dict))
        json_str = TypeAdapter(klass).dump_json(first_instance)
        second_instance = TypeAdapter(klass).validate_json(json_str)
        assert first_instance == second_instance

    do_submission_round_trip(Submission)
