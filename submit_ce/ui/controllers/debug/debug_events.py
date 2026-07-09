import json
from http import HTTPStatus as status
from typing import Tuple, Dict, Any

from flask import current_app
from werkzeug.datastructures import MultiDict

from arxiv.auth.domain import Session
from arxiv.base import logging

from submit_ce.implementations.legacy_implementation.models import DBEvent
from submit_ce.ui.backend import get_submission


Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103

logger = logging.getLogger(__name__)


def debug_events(method: str, params: MultiDict, session: Session,
                 submission_id: str, token: str, **kwargs) -> Response:  # pragma: no cover

    submission, _ = get_submission(submission_id)

    workspace = current_app.api.get_file_store().get_workspace(
        submission_id=submission.submission_id)

    def _decode(b):
        return json.loads(b) if b else None

    with current_app.api.get_session() as db_session:
        rows = (db_session.query(DBEvent)
                .filter(DBEvent.submission_id == submission_id)
                .order_by(DBEvent.created)
                .all())
        events = [{
            'event_id': r.event_id,
            'event_type': r.event_type,
            'created': r.created,
            'creator': _decode(r.creator),
            'proxy': _decode(r.proxy),
            'client': _decode(r.client),
            'data': _decode(r.data),
        } for r in rows]

    rdata = {
        'submission_id': submission_id,
        'submission': submission,
        'events' : events,
        'workspace': workspace,
        'form': None,
        'preflight_files': {},
        'file_notes': {},
    }
    logger.info(f'events: {events}')
    logger.info(f'submission: {dir(submission)}')

    logger.info(f'session: {dir(session)}')
    logger.info(f'session: {type(session)}')

    return (rdata, status.OK, {})
