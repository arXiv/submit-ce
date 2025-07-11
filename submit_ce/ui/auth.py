import logging
from typing import Callable, Tuple, Optional

from arxiv.auth.auth import tokens
from arxiv.auth.auth.exceptions import InvalidToken
from arxiv.auth.domain import Session
from arxiv.base.middleware import BaseMiddleware
from flask import request
from werkzeug.exceptions import InternalServerError, Unauthorized

from submit_ce.api import User, PublicUser, HttpClient, Client
from submit_ce.api.domain.agent import ServiceAgent, StaffUser, System
from submit_ce.ui.backend import get_endorsements
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
        token = token.removeprefix("Bearer ")
        
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


def _public_user(session: Session) -> bool:
    # TODO how to tell if session is EUST, mod or public user?
    return True


def _add_endorsements(user: User) -> None:
    """Adds endorsements to user."""
    if isinstance(user, (PublicUser, StaffUser)):
        user.endorsements.extend(get_endorsements(user))


def _get_user(session: Optional[Session]=None) -> User:
    if not session:
        session = request.environ['auth']  # was already setup by arxiv.auth.auth.middleware

    if not(session and session.user and session.user.user_id and session.authorizations):
        raise Unauthorized()

    if session.user.name:
        name = " ".join([session.user.name.forename, session.user.name.surname])
    else:
        name = "un-named user"

    # arxiv-base session usually lacks endorsements
    endorsements = getattr(session.authorizations, 'endorsements', [])

    # TODO handle staff users
    user = PublicUser(
        user_id=session.user.user_id,
        name=name,
        email=session.user.email,
        endorsements = endorsements,
        scopes = session.authorizations.scopes,
    )
    _add_endorsements(user)
    return user


def _get_client() -> HttpClient:
    # ua = request.headers.get("User-Agent", None)
    # if ua is None:
    #     agent_type = "ua-not-set"
    # if ua.lower().startswith("mozilla"):
    #     agent_type = "browser"
    # else:
    #     agent_type = ua[:20]

    # return HttpClient(
    #     remote_addr=request.remote_addr or "unknown-remote-addr",
    #     remote_host="",  # TODO get hostname
    # )
    # TODO implement _get_client
    return HttpClient(
        remote_addr= "unknown-remote-addr",
        remote_host=""
    )


def user_and_client_from_session(session: Session) \
        -> Tuple[User, Optional[Client]]:
    """
    Get submission user/client representations from a :class:`.Session`.

    When we're building submission-related events, we frequently need a
    submission-friendly representation of the user or client responsible for
    those events. This function generates those event-domain representations
    from a :class:`arxiv.users.domain.Submission` object.
    """

    # TODO: currently this does nothing with the client. We will need to add that
    # bit once we have a plan for handling client information in this interface.
    if not session or not session.user or not session.user.user_id or not session.user.profile:
        # TODO: fix this to handle SA or other non user clients
        raise RuntimeError("Must pass a valid `Session`")

    return _get_user(session), _get_client()
