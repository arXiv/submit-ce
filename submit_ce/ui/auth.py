from typing import Tuple, Optional

from arxiv.auth.domain import Session
from flask import request

from submit_ce.api import User
from submit_ce.api.domain import Client

import os
from typing import Callable, Iterable, Tuple
import jwt
import logging

from werkzeug.exceptions import Unauthorized, InternalServerError

from arxiv.base.middleware import BaseMiddleware, IWSGIApp

from arxiv.auth.auth import tokens
from arxiv.auth.auth.exceptions import InvalidToken, ConfigurationError, MissingToken
from arxiv.auth import domain
from submit_ce.ui.config import settings

logger = logging.getLogger(__name__)

WSGIRequest = Tuple[dict, Callable]


class SubmitAuthMiddleware(BaseMiddleware):
    def before(self, environ: dict, start_response: Callable) -> WSGIRequest:
        """Decode and unpack the auth token on the request."""
        if not settings.JWT_SECRET:
            raise InternalServerError("SECRET_KEY not set")

        environ['auth'] = None      # Create the session key, at a minimum.
        environ['token'] = None
        token = environ.get('HTTP_AUTHORIZATION', None)    # HTTP_AUTHORIZATION is the HTTP header Authorization        
        if not token:
            token = environ.get('ARXIVNG_SESSION_ID', None)
        if not token:
            logger.debug('No auth token')
            return environ, start_response

        try:
            environ['auth'] = tokens.decode(token, settings.JWT_SECRET)
            environ['token'] = token  # Attach the encrypted token so that we can use it in sub requests.
        except InvalidToken:   # Let the application decide what to do.
            logger.debug('Auth token not valid: %s', token)
            environ['auth'] = Unauthorized('Invalid auth token')
            environ['tokne'] = None
        except Exception as e:
            logger.error(f'Unhandled exception: {e}')
            environ['auth'] = InternalServerError(f'Unhandled: {e}')  # type: ignore
            environ['tokne'] = None
        return environ, start_response


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
    # TODO getting the remote_adder from flask in tests is broken
    # client.remote_addr = request.remote_addr  # not sure why it doesn't set in the constructor
    client.remote_addr = "127.0.0.1"
    client.hostname = ""
    return user, client

