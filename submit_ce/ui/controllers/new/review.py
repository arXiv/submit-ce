import logging
from collections import OrderedDict
from http import HTTPStatus as status
from locale import strxfrm
from pathlib import Path
from typing import Tuple, Dict, Any, Optional, List, Union

from flask import current_app
from arxiv.auth.domain import Session
from arxiv.base import alerts
from arxiv.forms import csrf
from markupsafe import Markup
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import (
    MethodNotAllowed,
)
from wtforms import SelectField
from wtforms.validators import DataRequired

from submit_ce.domain import Client, User, Event
from submit_ce.domain.event import SetUploadPackage, UpdateUploadPackage
from submit_ce.domain.submission import SubmissionContent, Submission
from submit_ce.domain.uploads import Workspace, FileStatus, UploadStatus
from submit_ce.domain.exceptions import SaveError
from submit_ce.ui.controllers.util import add_immediate_alert, validate_command
from submit_ce.ui.routes.flow_control import stay_on_this_stage
from submit_ce.ui.backend import get_submission
from submit_ce.ui import SUPPORT

from submit_ce.domain.compilation import Compilation

logger = logging.getLogger(__name__)

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103


class ReviewForm(csrf.CSRFForm):
    """Form for reviewing files and selecting compilation options."""
    
    # These choices will be populated dynamically in the controller
    source_file = SelectField('Select main source file', validators=[DataRequired()])
    compiler = SelectField('Select compiler', validators=[DataRequired()])
    compiler_version = SelectField('Select compiler version', validators=[DataRequired()])


def review_files(method: str, params: MultiDict, session: Session,
                 submission_id: str, **kwargs) -> Response:

    if method not in ['GET', 'POST']:
        raise MethodNotAllowed()

    submission, event_list = get_submission(submission_id)
    workspace = current_app.api.get_file_store().get_workspace(
        submission_id=submission.submission_id)

    form = ReviewForm(params)
    
    rdata = {
        'submission_id': submission_id,
        'submission': submission,
        'workspace': workspace,
        'form' : form,
    }


    # Did the user upload a 00RM
    # Is there already a 00RM
    # Is there already a preflight


    return stay_on_this_stage((rdata, status.OK, {}))
