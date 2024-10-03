"""Utilities and helpers for the :mod:`submit_ce` application."""

from typing import Optional, Tuple, List
from datetime import datetime

from flask import request
from werkzeug.exceptions import NotFound
from retry import retry

from arxiv.base import logging
from arxiv.base.globals import get_application_global
import submit_ce as events
from submit_ce.ui.domain import Event, Submission
from submit_ce.ui.exceptions import NoSuchSubmission

logger = logging.getLogger(__name__)
logger.propagate = False


#@retry(tries=2, delay=0.5, backoff=3, ) #exceptions=Unavailable)
def load_submission(submission_id: Optional[int]) \
        -> Tuple[Submission, List[Event]]:
    """
    Load a submission by ID.

    Parameters
    ----------
    submission_id : int

    Returns
    -------
    :class:`events.domain.Submission`

    Raises
    ------
    :class:`werkzeug.exceptions.NotFound`
        Raised when there is no submission with the specified ID.

    """
    if submission_id is None:
        raise NotFound('No submission id.')
    if hasattr(request, "submission") and request.submission is not None:
        if submission_id == request.submission.submission_id:
            return request.submission, []


def tidy_filesize(size: int) -> str:
    """
    Convert upload size to human readable form.

    Decision to use powers of 10 rather than powers of 2 to stay compatible
    with Jinja filesizeformat filter with binary=false setting that we are
    using in file_upload template.

    Parameter: size in bytes
    Returns: formatted string of size in units up through GB

    """
    units = ["B", "KB", "MB", "GB"]
    if size == 0:
        return "0B"
    if size > 1000000000:
        return '{} {}'.format(size, units[3])
    units_index = 0
    while size > 1000:
        units_index += 1
        size = round(size / 1000, 3)
    return '{} {}'.format(size, units[units_index])


# TODO: remove me!
def announce_submission(submission_id: int) -> None:
    """WARNING WARNING WARNING this is for testing purposes only."""
    dbss = events.services.classic._get_db_submission_rows(submission_id)
    head = sorted([o for o in dbss if o.is_new_version()], key=lambda o: o.submission_id)[-1]
    session = events.services.classic.current_session()
    if not head.is_announced():
        head.status = events.services.classic.models.Submission.ANNOUNCED
    if head.document is None:
        paper_id = datetime.now().strftime('%s')[-4:] \
            + "." \
            + datetime.now().strftime('%s')[-5:]
        head.document = \
            events.services.classic.models.Document(paper_id=paper_id)
        head.doc_paper_id = paper_id
    session.add(head)
    session.commit()


# TODO: remove me!
def place_on_hold(submission_id: int) -> None:
    """WARNING WARNING WARNING this is for testing purposes only."""
    dbss = events.services.classic._get_db_submission_rows(submission_id)
    i = events.services.classic._get_head_idx(dbss)
    head = dbss[i]
    session = events.services.classic.current_session()
    if head.is_announced() or head.is_on_hold():
        return
    head.status = events.services.classic.models.Submission.ON_HOLD
    session.add(head)
    session.commit()


# TODO: remove me!
def apply_cross(submission_id: int) -> None:
    session = events.services.classic.current_session()
    dbss = events.services.classic._get_db_submission_rows(submission_id)
    i = events.services.classic._get_head_idx(dbss)
    for dbs in dbss[:i]:
        if dbs.is_crosslist():
            dbs.status = events.services.classic.models.Submission.ANNOUNCED
            session.add(dbs)
            session.commit()


# TODO: remove me!
def reject_cross(submission_id: int) -> None:
    session = events.services.classic.current_session()
    dbss = events.services.classic._get_db_submission_rows(submission_id)
    i = events.services.classic._get_head_idx(dbss)
    for dbs in dbss[:i]:
        if dbs.is_crosslist():
            dbs.status = events.services.classic.models.Submission.REMOVED
            session.add(dbs)
            session.commit()


# TODO: remove me!
def apply_withdrawal(submission_id: int) -> None:
    session = events.services.classic.current_session()
    dbss = events.services.classic._get_db_submission_rows(submission_id)
    i = events.services.classic._get_head_idx(dbss)
    for dbs in dbss[:i]:
        if dbs.is_withdrawal():
            dbs.status = events.services.classic.models.Submission.ANNOUNCED
            session.add(dbs)
            session.commit()


# TODO: remove me!
def reject_withdrawal(submission_id: int) -> None:
    session = events.services.classic.current_session()
    dbss = events.services.classic._get_db_submission_rows(submission_id)
    i = events.services.classic._get_head_idx(dbss)
    for dbs in dbss[:i]:
        if dbs.is_withdrawal():
            dbs.status = events.services.classic.models.Submission.REMOVED
            session.add(dbs)
            session.commit()
