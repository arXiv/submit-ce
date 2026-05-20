from sqlalchemy.orm import Session as SQLAlchemySession

from submit_ce.domain import Submission
from submit_ce.implementations.legacy_implementation.db import _get_db_submission_rows, _get_head_idx

def place_on_hold(session: SQLAlchemySession, submission_id: str) -> None:
    """WARNING WARNING WARNING this is for testing purposes only."""
    dbss = _get_db_submission_rows(session, submission_id)
    i = _get_head_idx(session, dbss)
    head = dbss[i]
    if head.is_announced() or head.is_on_hold():
        return
    head.status = Submission.ON_HOLD
    session.add(head)
    session.commit()

def apply_cross(session: SQLAlchemySession, submission_id: str) -> None:
    """WARNING WARNING WARNING this is for testing purposes only."""

    dbss = _get_db_submission_rows(session, submission_id)
    i = _get_head_idx(session, dbss)
    for dbs in dbss[:i]:
        if dbs.is_crosslist():
            dbs.status = Submission.ANNOUNCED
            session.add(dbs)
            session.commit()


def reject_cross(session: SQLAlchemySession, submission_id: str) -> None:
    """WARNING WARNING WARNING this is for testing purposes only."""

    dbss = _get_db_submission_rows(session, submission_id)
    i = _get_head_idx(session, dbss)
    for dbs in dbss[:i]:
        if dbs.is_crosslist():
            dbs.status = Submission.REMOVED
            session.add(dbs)
            session.commit()


def apply_withdrawal(session: SQLAlchemySession, submission_id: str) -> None:
    """WARNING WARNING WARNING this is for testing purposes only."""

    dbss = _get_db_submission_rows(session, submission_id)
    i = _get_head_idx(session, dbss)
    for dbs in dbss[:i]:
        if dbs.is_withdrawal():
            dbs.status = Submission.ANNOUNCED
            session.add(dbs)
            session.commit()


def reject_withdrawal(session: SQLAlchemySession, submission_id: str) -> None:
    """WARNING WARNING WARNING this is for testing purposes only."""

    dbss = _get_db_submission_rows(session, submission_id)
    i = _get_head_idx(session, dbss)
    for dbs in dbss[:i]:
        if dbs.is_withdrawal():
            dbs.status = Submission.REMOVED
            session.add(dbs)
            session.commit()
