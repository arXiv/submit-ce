import logging
from typing import Callable, Tuple, Optional

from arxiv.auth.legacy import util
from arxiv.db.models import Demographic, TapirNickname, TapirUser
from arxiv.db import Session as DB  # renamed due to too many session
from flask import request
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import Unauthorized, NotFound
from werkzeug.http import parse_cookie

from arxiv.auth.auth import tokens
from arxiv.auth.auth.exceptions import ExpiredToken, InvalidToken, MissingToken, SessionCreationFailed
from arxiv.auth import domain as auth_domian

from submit_ce.api import User, PublicUser, HttpClient, Client
from submit_ce.api.domain.agent import StaffUser
from submit_ce.ui import backend
from submit_ce.ui.backend import get_endorsements
from submit_ce.ui.config import settings

logger = logging.getLogger(__name__)


def _ip_address(environ) -> str:
    try:
        return environ['HTTP_X_FORWARDED_FOR'].split(',')[-1].strip()
    except KeyError:
        return environ['REMOTE_ADDR']

def _get_cookies(environ) -> list[str]:
    """Get all cookies with key ARXIVNG_SESSION_ID."""
    raw_cookie = environ.get('HTTP_COOKIE', None)
    if not raw_cookie:
        return []
    cookies = parse_cookie(raw_cookie, cls=MultiDict)    
    return cookies.getlist("ARXIVNG_SESSION_ID")

def _get_auth_bearer(environ) -> list[str]:
    bearer = environ.get('HTTP_AUTHORIZATION', None)
    if not bearer:
        return []
    else:
        return [bearer.strip().removeprefix("Bearer ").strip()]


def _get_first_valid_jwt(secret, cookies) -> Tuple[auth_domian.Session, str]:
    """Get the first cookie that decodes as a JWT with the secret."""
    if not cookies:
        raise MissingToken
    
    for cookie in cookies:
        try:    
            jwt_data = tokens.decode(cookie, secret)
            if jwt_data:
                return jwt_data, cookie
        except(InvalidToken):
            continue

    raise InvalidToken(f"Only invalid tokens found in {len(cookies)}")
    
def _session_from_db(jwt: auth_domian.Session) -> auth_domian.Session:
    """Gets a user from the db.

    Uses endorsements and scopes from db, not from jwt since jwt seems not record these.
    """
    ip = _ip_address(request.environ)
    if not jwt or not jwt.user or not jwt.user.user_id:
        raise SessionCreationFailed(f"no session or no user. ip {ip}")
    user_id = jwt.user.user_id
    if jwt.expired:
        raise ExpiredToken(f'JWT has an expired session {jwt.session_id} user {user_id} ip {ip}')    

    data: Tuple[TapirUser, TapirNickname, Demographic] = \
    DB.query(
          TapirUser, TapirNickname, Demographic) \
          .join(TapirNickname).join(Demographic) \
          .filter(TapirUser.user_id == user_id) \
          .first()

    if not data or len(data) != 3 or not data[0]:
        raise SessionCreationFailed(f'No such user {user_id}')
    db_user, db_nick, db_profile = data

    user = auth_domian.User(
        user_id=str(user_id),
        username=db_nick.nickname,
        email=db_user.email,
        name=auth_domian.UserFullName(
            forename=db_user.first_name or "",
            surname=db_user.last_name or "",
            suffix=db_user.suffix_name
        ),
        profile=auth_domian.UserProfile.from_orm(db_profile) if db_profile else None,
        verified=bool(db_user.flag_email_verified)
    )
    authorizations = auth_domian.Authorizations(
        classic=util.compute_capabilities(db_user),
        scopes=util.get_scopes(db_user)
    )
    db_session = auth_domian.Session(session_id=jwt.session_id,
                                       start_time=jwt.start_time, end_time=jwt.end_time,
                                       user=user, authorizations=authorizations)
    logger.debug('loaded user %s', db_session.user.user_id)
    return db_session


    
def setup_auth():
    """For use with `@app.before_reqeust()` to add auth attributes to `request`.

    Must be run inside a flask request context."""
    session, token = _get_first_valid_jwt(settings.JWT_SECRET,
                                          _get_cookies(request.environ) + _get_auth_bearer(request.environ))
    request.environ['token'] = token  # Attach the encrypted token for use in sub requests
    setattr(request,"auth", _session_from_db(session))


def _add_endorsements(user: User) -> None:
    """Adds endorsements to user."""
    if isinstance(user, (PublicUser, StaffUser)):
        if user.endorsements:
            user.endorsements.extend(get_endorsements(user))
        else:
            user.endorsements = get_endorsements(user)


def _get_user(session: Optional[auth_domian.Session]=None) -> User:
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


def _get_client(session: auth_domian.Session) -> HttpClient:
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
        remote_addr= session.ip_address or "",
        remote_host= ""
    )


def user_and_client_from_session(session: auth_domian.Session) -> Tuple[User, Optional[Client]]:
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

    return _get_user(session), _get_client(session)


def is_owner(session: auth_domian.Session, submission_id: str, **kw) -> bool:
    """Check whether the user has privileges to edit a submission."""
    submission, _ = backend.get_submission(int(submission_id))
    if not submission:
        raise NotFound('No such submission')
    logger.debug('Submission owned by %s; request is from %s',
                 submission.owner.identifier,
                 session.user.user_id)
    return str(submission.owner.user_id) == str(session.user.user_id)
