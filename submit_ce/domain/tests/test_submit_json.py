from submit_ce.domain import Submission
from polyfactory.factories import DataclassFactory
from pydantic import TypeAdapter

def test_roundtrip_submission_to_json_polyfactory():
    class SubmissionFactory(DataclassFactory[Submission]):
        pass

    for _ in range(30):
        first_json_str = TypeAdapter(Submission).dump_json(SubmissionFactory.build())
        second_inst = TypeAdapter(Submission).validate_json(first_json_str)
        assert first_json_str == TypeAdapter(Submission).dump_json(second_inst)
