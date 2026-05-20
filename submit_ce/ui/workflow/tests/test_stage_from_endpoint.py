"""Test getting stage from endpoint."""
# tests/ui/workflow/test_stage_from_endpoint.py
import pytest
from submit_ce.ui.workflow import WorkflowDefinition
from submit_ce.ui.workflow.stages import Stage

class P(Stage):
    endpoint = "p"
    label = "P"
    def is_complete(self, sub): return True
    def incomplete(self, sub): return []

def test_stage_from_endpoint_and_error():
    wf = WorkflowDefinition("WF", order=[P()], confirmation=P())
    assert type(wf.stage_from_endpoint("p")).__name__ == "P"
    with pytest.raises(ValueError):
        wf.stage_from_endpoint("nope")
