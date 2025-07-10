import logging
from typing import Callable, Tuple

from arxiv.auth.auth import tokens
from arxiv.auth.auth.exceptions import InvalidToken
from arxiv.auth.domain import Session
from arxiv.base.middleware import BaseMiddleware
from werkzeug.exceptions import InternalServerError, Unauthorized

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
