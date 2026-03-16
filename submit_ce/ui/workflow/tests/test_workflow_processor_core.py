""" Additional workflow test, finalize and complete submission."""
import pytest
from flask import current_app

from submit_ce.ui.workflow import WorkflowDefinition
from submit_ce.ui.workflow.processor import WorkflowProcessor
from submit_ce.ui.workflow.stages import (
    VerifyUser, Agreement, License, Classification,
    FileUpload, ReviewFiles, Process, Metadata,
    OptionalMetadata, FinalPreview, Confirm
)

from submit_ce.api.domain.agent import InternalClient
from submit_ce.api.domain.event import FinalizeSubmission


@pytest.mark.usefixtures("app")
def test_workflow_processor_paths(sub_metadata, authorized_user, app):
    """
    Verify WorkflowProcessor:
      - Picks the first incomplete real stage
      - Reports complete only after FinalPreview (is_finalized) is satisfied
    """

    # Build a realistic workflow using existing stages (as in production)
    wf = WorkflowDefinition(
        "WF",
        order=[
            VerifyUser(),
            Agreement(),
            License(),
            Classification(),
            FileUpload(),
            ReviewFiles(),
            Process(),
            Metadata(),
            OptionalMetadata(),
            FinalPreview(),   # <- this will be the first incomplete stage pre-finalization
            Confirm(),        # confirmation step
        ],
        confirmation=Confirm(),
    )

    submission = sub_metadata  # Not finalized yet

    proc = WorkflowProcessor(workflow=wf, submission=submission)

    # Workflow should not be complete
    assert proc.is_complete() is False

    # First incomplete stage should be FinalPreview, because all earlier
    # stages' .completed predicates evaluate to True on sub_metadata.
    assert type(proc.current_stage()).__name__ == "FinalPreview"

    # ---- Finalize Submission ----
    with app.app_context():
        creator = authorized_user
        client = InternalClient(name="test-client")
        submission, _ = current_app.api.save(
            FinalizeSubmission(creator=creator, client=client),
            submission_id=submission.submission_id,
        )

    # Now workflow should be complete
    proc2 = WorkflowProcessor(workflow=wf, submission=submission)
    assert proc2.is_complete() is True