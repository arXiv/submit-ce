from flask import current_app

from submit_ce.domain.agent import InternalClient
from submit_ce.domain.event import CreateSubmission


def test_create_submission_event_round_trips(app, authorized_user):
    """`api.save(CreateSubmission)` should persist the event so that
    `api.get_with_history` returns it on a fresh read."""
    with app.app_context():
        client = InternalClient(name="test_event_persistence")
        submission, _ = current_app.api.save(
            CreateSubmission(creator=authorized_user, client=client)
        )

        _, history = current_app.api.get_with_history(str(submission.submission_id))

        create_events = [e for e in history if isinstance(e, CreateSubmission)]
        assert len(create_events) == 1
        assert create_events[0].creator.user_id == authorized_user.user_id
