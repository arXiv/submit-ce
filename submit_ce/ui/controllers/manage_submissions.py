"""Controller for 'Manage Submissions' page."""

from http import HTTPStatus as status
from pathlib import Path
import subprocess

from arxiv.auth.domain import Session
from arxiv.forms import csrf
from flask import url_for, current_app
from werkzeug.datastructures import MultiDict

from submit_ce.domain.event import CreateSubmission

from submit_ce.ui.auth import user_and_client_from_session
from submit_ce.ui.controllers.util import validate_command
from submit_ce.ui.routes.flow_control import advance_to_current, Response


class CreateSubmissionForm(csrf.CSRFForm):
    """Submission creation form."""


def manage_submissions(method: str, params: MultiDict, session: Session, *args,
           **kwargs) -> Response:
    """Create a new submission, and redirect to workflow."""
    submitter, client = user_and_client_from_session(session)
    response_data = {}
    if method == 'GET':
        response_data['user_submissions'] = current_app.api.load_submissions_for_user(session.user.user_id)
        response_data['submitter'] = submitter
        params = MultiDict()

    form = CreateSubmissionForm(params)  # We're using a form here for CSRF protection of create
    response_data['form'] = form
    response_data['submit_version'] = _version()

    command = CreateSubmission(creator=submitter, client=client)
    if method == 'POST' and form.validate() and validate_command(form, command):
        submission, _ = current_app.api.save(command)
        # TODO Do we need a better way to enter a workflow?
        # Maybe a controller that is defined as the entrypoint?
        loc = url_for('ui.verify_user', submission_id=submission.submission_id)
        return {}, status.SEE_OTHER, {'Location': loc}

    return advance_to_current((response_data, status.OK, {}))

_GIT_FILE="git_commit.txt"
_git_version = None

def _version():
    global _git_version
    if _git_version:
        return _git_version
    else:
        file = Path(_GIT_FILE)
        if file.exists():
            with open("git_commit.txt", 'r') as file:
                _git_version = file.read()
        if not _git_version:
             try:
                # {tag}-{commits-since-tag}-{short-commit-hash}-{dirty}
                command = ['git', 'describe', '--tags', '--long', '--dirty']
                git_string_bytes = subprocess.check_output(command, stderr=subprocess.STDOUT)
                _git_version = git_string_bytes.decode('utf-8').strip()
             except subprocess.CalledProcessError:
                 _git_version = "not-git-repo"
             except FileNotFoundError:
                 _git_version = "git-not-installed"

        return _git_version
