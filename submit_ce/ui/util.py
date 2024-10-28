"""Utilities and helpers for the :mod:`submit_ce` application."""

from typing import Optional, Tuple, List

from flask import request
from werkzeug.exceptions import NotFound

from arxiv.base import logging

from submit_ce.api.domain.event import Event
from submit_ce.api.domain import Submission

logger = logging.getLogger(__name__)
logger.propagate = False


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


