"""Authorization helpers for :mod:`submit_ce` application."""
from arxiv.auth.domain import Session
from flask import request
from werkzeug.exceptions import NotFound

from arxiv.base import logging

from submit_ce.ui import backend

logger = logging.getLogger(__name__)
logger.propagate = False


# TODO: when we get to the point where we need to support delegations, this will need to be updated.
def is_owner(session: Session, submission_id: str, **kw) -> bool:
    """Check whether the user has privileges to edit a submission."""
    submission, events = backend.get_submission(int(submission_id))
    if not submission:
        logger.debug('No submission on request')
        raise NotFound('No such submission')
    logger.debug('Submission owned by %s; request is from %s',
                 submission.owner.native_id,
                 session.user.user_id)
    return str(submission.owner.native_id) == str(session.user.user_id)
