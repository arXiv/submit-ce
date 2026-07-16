"""
Provides the final preview and confirmation step.
"""

from http import HTTPStatus as status
from typing import Tuple, Dict, Any

from arxiv.auth.domain import Session
from arxiv.base import logging
from arxiv.forms import csrf
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import InternalServerError
from wtforms import BooleanField
from wtforms.validators import InputRequired
from flask import current_app

from submit_ce.ui.auth import user_and_client_from_session
from submit_ce.domain.event import FinalizeSubmission
from submit_ce.domain.exceptions import SaveError
from submit_ce.ui.controllers.util import validate_command
from submit_ce.ui.routes.flow_control import ready_for_next, stay_on_this_stage
from submit_ce.ui.backend import get_submission


logger = logging.getLogger(__name__)  # pylint: disable=C0103

Response = Tuple[Dict[str, Any], int, Dict[str, Any]]  # pylint: disable=C0103


def _upload_qa_metadata(file_store, submission_id: str) -> None:
    """Build and upload the QA submission-snapshot meta.json after finalize.

    Best-effort: a failure here must never fail the submission itself, so any
    exception is logged and swallowed. Gated by ``QA_GS_UPLOAD_ENABLED``.
    """
    from submit_ce.ui.config import settings
    if not settings.QA_GS_UPLOAD_ENABLED:
        return
    try:
        from submit_ce.ui.controllers.qa_metadata import build_qa_metadata
        file_store.store_qa_metadata(submission_id, build_qa_metadata(submission_id))
    except Exception:  # noqa: BLE001 - QA upload must not break finalize
        logger.exception("Failed to upload QA metadata for %s", submission_id)


def _pubsub_qa_metadata(submission_id: str) -> None:
    """Publish the QA submission-snapshot metadata to Pub/Sub after finalize.

    Best-effort: a failure here must never fail the submission itself, so any
    exception is logged and swallowed. Gated by ``QA_PUBSUB_ENABLED``.
    """
    import json
    from submit_ce.ui.config import settings
    if not settings.QA_PUBSUB_ENABLED or not settings.QA_PUBSUB_TOPIC:
        return
    try:
        from google.cloud import pubsub_v1
        from submit_ce.ui.controllers.qa_metadata import build_qa_metadata
        metadata = build_qa_metadata(submission_id)
        publisher = pubsub_v1.PublisherClient()
        future = publisher.publish(
            settings.QA_PUBSUB_TOPIC,
            json.dumps(metadata).encode("utf-8"))
        future.result(timeout=60)
    except Exception:  # noqa: BLE001 - QA pubsub must not break finalize
        logger.exception("Failed to publish QA metadata for %s", submission_id)


def finalize(method: str, params: MultiDict, session: Session,
             submission_id: str, **kwargs) -> Response:
    submitter, _ = user_and_client_from_session(session)

    logger.debug(f'method: {method}, ui-app: {submission_id}. {params}')
    submission, submission_events = get_submission(submission_id)

    form = FinalizationForm(params)

    # Check whether a preview PDF actually exists in the bucket. The
    # persisted submitter_confirmed_preview flag can drift from file-store
    # reality (e.g., a PDF was removed out-of-band, a file-change event
    # missed resetting the flag, or in dev when state is manipulated
    # directly). The Confirm page should gate Submit on what's actually
    # in the bucket, not just the persisted flag, so an absent PDF can
    # never produce an enabled Submit button.
    file_store = current_app.api.get_file_store()
    preview_exists = file_store.does_preview_exist(str(submission_id))
    preview_ready = bool(submission.submitter_confirmed_preview
                         and preview_exists)
    logger.info(
        "finalize: submission=%s confirmed_preview=%s preview_exists=%s "
        "preview_ready=%s",
        submission_id, submission.submitter_confirmed_preview,
        preview_exists, preview_ready,
    )

    # The abs preview macro expects a specific struct for submission history.
    # TODO submission.versions removed, what do do in final?
    # submission_history = [{'submitted_date': s.created, 'version': s.version}
    #                      for s in submission.versions]
    submission_history = []
    response_data = {
        'submission_id': submission_id,
        'form': form,
        'submission': submission,
        'submitter': submitter,
        'submission_history': submission_history,
        'preview_ready': preview_ready,
        'preview_exists': preview_exists,
    }

    # Only treat this POST as an actual submit attempt when the form's
    # "next" action was used. The Confirm form is shared by the nav bar's
    # "Go Back" and "Save & Exit" buttons too -- those also POST the form
    # (so the CSRF token comes along) but they're navigation actions, not
    # the submit action. If the user has the proofread checkbox ticked and
    # then clicks Go Back, we must NOT fire FinalizeSubmission; flow_control
    # is supposed to redirect them to the previous step instead.
    action = (params.get('action') or '').strip()
    is_submit_action = action == 'next'

    command = FinalizeSubmission(creator=submitter)
    proofread_confirmed = form.proceed.data
    if method == 'POST' and is_submit_action \
       and form.validate() \
       and proofread_confirmed \
       and validate_command(form, command, submission):
        try:
            submission, stack = current_app.api.save(  # pylint: disable=W0612
                command, submission_id=submission_id)
        except SaveError as e:
            logger.error('Could not save primary event')
            raise InternalServerError(response_data) from e
        _upload_qa_metadata(file_store, submission_id)
        _pubsub_qa_metadata(submission_id)
        return ready_for_next((response_data, status.OK, {}))
    else:
        return stay_on_this_stage((response_data, status.OK, {}))

    return response_data, status.OK, {}


class FinalizationForm(csrf.CSRFForm):
    """Make sure the user is really really really ready to submit."""

    proceed = BooleanField(
        'By checking this box, I confirm that I have reviewed my submission as'
        ' it will appear on arXiv.',
        [InputRequired('Please confirm that the submission is ready')]
    )


def confirm(method: str, params: MultiDict, session: Session,
            submission_id: str, **kwargs) -> Response:
    submission, _ = get_submission(submission_id)
    submitter, _ = user_and_client_from_session(session)

    response_data = {
        'submission_id': submission_id,
        'submission': submission,
        'submitter': submitter,
    }
    return response_data, status.OK, {}
