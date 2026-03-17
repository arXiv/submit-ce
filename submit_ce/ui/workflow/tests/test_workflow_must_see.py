"""Test behavior when must seen is set"""
import pytest
from submit_ce.ui.workflow import ReplacementWorkflow
from submit_ce.ui.workflow.processor import WorkflowProcessor

@pytest.mark.usefixtures("app")
def test_must_see_forces_visitation(sub_metadata):
    wf = ReplacementWorkflow
    proc = WorkflowProcessor(workflow=wf, submission=sub_metadata)

    # First stage must be seen even if predicates are satisfied
    first = proc.current_stage()
    assert type(first).__name__ == "VerifyUser"

    # After marking seen, the processor should advance
    proc.mark_seen(first)
    assert type(proc.current_stage()).__name__ != "VerifyUser"
