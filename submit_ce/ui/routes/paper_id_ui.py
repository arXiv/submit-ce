"""Provides routes that are keyed on a paper id rather than a submission id.

Most of the UI operates on a submission being edited, so its routes take a
``submission_id`` (see :mod:`.ui`). A few operations are instead about an
*announced paper* and create a submission of their own; those live here and take
a ``paper_id``.

The paper id is matched with the ``path`` converter because old-style arXiv
identifiers contain a slash (``hep-th/9901001``).
"""

import logging
from typing import Union

from arxiv.auth.auth import scopes
from arxiv.auth.auth.decorators import scoped
from flask import Blueprint
from werkzeug import Response as WResponse
from flask import Response as FResponse

from submit_ce.ui import controllers as cntrls
from submit_ce.ui.auth import is_paper_owner
from .ui import handle, redirect_to_login


logger = logging.getLogger(__name__)

PAPER_ID_UI = Blueprint('paper', __name__, url_prefix='/')
"""Paper-keyed routes.

A blueprint of its own, and so a name of its own: Flask will not register two
blueprints under the same name, and ``ui`` is taken by :data:`.ui.UI`.
Endpoints here are ``paper.*`` in ``url_for``.
"""

Response = Union[FResponse, WResponse]


@PAPER_ID_UI.route('/<path:paper_id>/add_jref', methods=["POST"])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_paper_owner,
        unauthorized=redirect_to_login)
def add_jref(paper_id: str) -> Response:
    """Create a journal reference submission for an announced paper.

    Creating one is a write, so this is POST only; the dashboard links to it
    with a form button. On success the user is redirected to the new jref's own
    edit page (``ui.jref``). The template named here is only rendered when the
    paper cannot take a journal reference right now.
    """
    return handle(cntrls.jref.add_jref, 'submit/submission_blocked.html',
                  'Add journal reference', None, paper_id=paper_id)


@PAPER_ID_UI.route('/<path:paper_id>/add_cross', methods=["POST"])
@scoped(scopes.EDIT_SUBMISSION, authorizer=is_paper_owner,
        unauthorized=redirect_to_login)
def add_cross(paper_id: str) -> Response:
    """Create a cross-list submission for an announced paper.

    POST only for the same reason as :func:`add_jref`; the dashboard links here
    with a form button. On success the user is redirected to the new cross's own
    edit page (``ui.cross``) to choose categories. The template named here is
    only rendered when the paper cannot be cross-listed right now.
    """
    return handle(cntrls.cross.add_cross, 'submit/submission_blocked.html',
                  'Add cross-list', None, paper_id=paper_id)
