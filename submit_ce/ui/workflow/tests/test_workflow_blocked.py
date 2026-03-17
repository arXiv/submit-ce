"""Test blocked on finalize."""
import pytest
from submit_ce.ui.workflow import WorkflowDefinition
from submit_ce.ui.workflow.stages import (
    VerifyUser, Agreement, License, Classification,
    FileUpload, ReviewFiles, Process, Metadata, FinalPreview, Confirm
)
from submit_ce.ui.workflow.processor import WorkflowProcessor

@pytest.mark.usefixtures("app")
def test_blocked_rules(sub_metadata):
    wf = WorkflowDefinition(
        "WF",
        order=[VerifyUser(), Agreement(), License(), Classification(),
               FileUpload(), ReviewFiles(), Process(), Metadata(), FinalPreview()],
        confirmation=Confirm(),
    )
    proc = WorkflowProcessor(workflow=wf, submission=sub_metadata)

    # Confirmation is blocked by FinalPreview (not finalized yet)
    blocks = dict(proc.blocked(wf.confirmation))
    assert "FinalPreview" in blocks
