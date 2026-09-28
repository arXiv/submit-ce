"""Stages that do not apply to a submission are passed over. [SUBMISSION-127]"""
from http import HTTPStatus as status

from flask import current_app

from submit_ce.ui.tests.csrf_util import parse_csrf_token
from submit_ce.ui.workflow import NewSubmissionWorkflow, ReplacementWorkflow
from submit_ce.ui.workflow.processor import WorkflowProcessor
from submit_ce.ui.workflow.stages import FileUpload, Metadata, Process, ReviewFiles


def _processor(app, submission, workflow=NewSubmissionWorkflow):
    with app.app_context():
        _, events = current_app.api.get_with_history(str(submission.submission_id))
    return WorkflowProcessor(workflow, submission, events)


def test_html_passes_over_review_files_and_process(app, sub_files_html):
    proc = _processor(app, sub_files_html)
    wf = proc.workflow
    assert proc.next_stage(wf[FileUpload]) == wf[Metadata]
    assert proc.previous_stage(wf[Metadata]) == wf[FileUpload]


def test_passed_over_stages_need_not_be_seen(app, sub_files_html):
    """Replacement stages must be seen, but the submitter never visits these."""
    proc = _processor(app, sub_files_html, ReplacementWorkflow)
    wf = proc.workflow
    assert proc.is_done(wf[ReviewFiles]) and proc.is_done(wf[Process])
    assert not [name for name, _ in proc.blocked(wf[Metadata])
                if name in ("ReviewFiles", "Process")]


def test_tex_still_goes_through_review_files(app, sub_files_tex):
    proc = _processor(app, sub_files_tex)
    wf = proc.workflow
    assert proc.next_stage(wf[FileUpload]) == wf[ReviewFiles]


def test_back_from_metadata_reaches_upload_for_html(authorized_client, sub_files_html):
    """Before, Back went to Process, which sent the submitter on to Metadata again."""
    url = f"/{sub_files_html.submission_id}/add_metadata"
    page = authorized_client.get(url)
    resp = authorized_client.post(url, data={"action": "previous",
                                             "csrf_token": parse_csrf_token(page)})
    assert resp.status_code == status.SEE_OTHER
    assert resp.headers["Location"].endswith("/file_upload")


def test_a_passed_over_stage_moves_on(authorized_client, sub_files_html, mocker):
    compile_ = mocker.patch("submit_ce.ui.controllers.new.process.start_compilation")
    resp = authorized_client.get(f"/{sub_files_html.submission_id}/file_process")
    assert resp.status_code == status.SEE_OTHER
    assert resp.headers["Location"].endswith("/add_metadata")
    compile_.assert_not_called()
