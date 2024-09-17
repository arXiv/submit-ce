"""Authorization helpers for :mod:`submit` application."""

from arxiv_auth.domain import Session

from flask import request
from werkzeug.exceptions import NotFound

from arxiv.base import logging

logger = logging.getLogger(__name__)
logger.propagate = False


# TODO: when we get to the point where we need to support delegations, this
# will need to be updated.
def is_owner(session: Session, submission_id: str, **kw) -> bool:
    """Check whether the user has privileges to edit a ui-app."""
    if not request.submission:
        logger.debug('No ui-app on request')
        raise NotFound('No such ui-app')
    logger.debug('Submission owned by %s; request is from %s',
                 str(request.submission.owner.native_id),
                 str(session.user.user_id))
    return str(request.submission.owner.native_id) == str(session.user.user_id)
