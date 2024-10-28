from typing import Tuple, Optional

from arxiv.auth.domain import Session
from flask import request

from submit_ce.api import User
from submit_ce.api.domain import Client


def user_and_client_from_session(session: Session) \
        -> Tuple[User, Optional[Client]]:
    """
    Get submission user/client representations from a :class:`.Session`.

    When we're building submission-related events, we frequently need a
    submission-friendly representation of the user or client responsible for
    those events. This function generates those event-domain representations
    from a :class:`arxiv.users.domain.Submission` object.
    """

    # TODO: remove me!
    # TODO: currently this does nothing with the client. We will need to add that
    # bit once we have a plan for handling client information in this interface.

    user = User(
        session.user.user_id,
        email=session.user.email,
        forename=getattr(session.user.name, 'forename', None),
        surname=getattr(session.user.name, 'surname', None),
        suffix=getattr(session.user.name, 'suffix', None),
        # TODO where are endorsements other than the db? are they submission groups in the jwt?
        #  from the legacy.db and jwt from tests/make_test_db.py I'm not getting endorsements
        endorsements=["cs.CV", "cs.LG", "math.PR", ],
    )
    client = Client(
        "totally_fake_cliet_native_id",
    )
    client.remote_addr = request.remote_addr # not sure why it doesn't set in the constructor
    client.hostname = ""
    return user, client

