from datetime import datetime, timezone
import logging
from typing import Callable, Tuple, Optional

import jwt

from arxiv.auth.legacy import util
from arxiv.db.models import Demographic, TapirNickname, TapirUser
from arxiv.db import Session as DB  # renamed due to too many session
from flask import has_app_context, has_request_context, request
from pydantic_core import ValidationError
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import Unauthorized, NotFound
from werkzeug.http import parse_cookie

from arxiv.auth.auth.tokens import decode
from arxiv.auth.auth.exceptions import ExpiredToken, InvalidToken, MissingToken, SessionCreationFailed
from arxiv.auth import domain as auth_domian
from arxiv.auth.legacy.endorsements import explicit_endorsements

from submit_ce.api import User, PublicUser, HttpClient, Client
from submit_ce.api.domain.agent import StaffUser
from submit_ce.ui import backend, get_device_type, is_admin
from submit_ce.ui.config import settings

logger = logging.getLogger(__name__)


def _to_datetime(time:str|int|datetime|None)-> datetime:
    if isinstance(time, datetime):
        return time
    if isinstance(time, str) and time:
        return datetime.fromisoformat(time)
    if isinstance(time, int):
        return datetime.fromtimestamp(time, tz=timezone.utc)
    else:
        return datetime.fromtimestamp(0, tz=timezone.utc)


def _ip_address() -> str:
    environ = request.environ
    try:
        return environ['HTTP_X_FORWARDED_FOR'].split(',')[-1].strip()
    except KeyError:
        return getattr(environ,'REMOTE_ADDR', "unknown")


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


def _session_from_db(user_id, session_id,
                     end_iso: str|int|datetime, start_iso: str|int|datetime = "",
                     ip: Optional[str] = None) -> auth_domian.Session:
    """Gets a `arxiv.auth.domian.Session` from the db.

    Uses endorsements and scopes from db, not from jwt since jwt seems not record these.
    """
    expires = _to_datetime(end_iso)
    start = _to_datetime(start_iso)
    if expires < datetime.now(tz=timezone.utc):
        raise ExpiredToken(f'JWT has an expired session {session_id} user {user_id}')

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

    db_session = auth_domian.Session(user=user, session_id=session_id,
                                     start_time=start, end_time=expires,
                                     authorizations=authorizations)
    logger.debug('loaded user %s', user_id)
    db_session.ip_address = ip if ip else _ip_address()
    return db_session
    

def _modern_auth(tokens: list[str]) -> Tuple[auth_domian.Session, str]:
    """Try to deocde jwt to `auth_domain.Session` using code from `arxiv.auth.auth.tokens`.

    This is the kind of code we should move to once auth if finished."""
    if not tokens:
        raise MissingToken()
    session, token = None, None
    for jwt_orig in tokens:
        try:    
            jwt_data = decode(jwt_orig, settings.JWT_SECRET)
            if jwt_data:
                session, token = jwt_data, jwt_orig
                break
        except(InvalidToken):
            continue
    if not session or not token or not session.user or not session.user.user_id:
        raise Unauthorized("no invalid token or cookie")

    user_id = session.user.user_id
    if session.expired:
        raise ExpiredToken(f'JWT has an expired session {session.session_id} user {user_id}'\
                           f'ip {session.ip_address}')

    db_session = _session_from_db(session.user.user_id, session.session_id,
                                  session.end_time, session.start_time,
                                  session.ip_address)
    return db_session, token

    
def _ng_dict_jwt_auth(tokens: list[str]) -> Tuple[auth_domian.Session, str]:
    """Try to decode jwt just to a dict and use that to auth.

    This code should be retired once keycloak and related services are working.

    NG loggin doesn't seem to make a full JWT so the arxiv.auth.auth.tokens fails
    with a pydantic error.

    Example data:

       {
         'user_id': '1234',
         'session_id': '596b995b-7907-411e-9551-375f95c471d2',
         'nonce': '22307705',
         'expires': '2025-07-26T19:42:22.218281+00:00'
        }
    """
    if not tokens:
        raise MissingToken()
    session, token = None, None
    for jwt_orig in tokens:
        try:
            jwt_data = dict(jwt.decode(jwt_orig, settings.JWT_SECRET, algorithms=['HS256']))
            if jwt_data:
                session, token = jwt_data, jwt_orig
        except jwt.DecodeError:
            continue
    if (not session or not token or "user_id" not in session or "session_id"
        not in session or "expires" not in session):
        raise Unauthorized("no invalid token or cookie")

    user_id = session["user_id"]
    session_id = session["session_id"]
    expires = datetime.fromisoformat(session["expires"])
    if expires < datetime.now(tz=timezone.utc):
        raise ExpiredToken(f'JWT has an expired session {session_id} user {user_id}')

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
    epoch_start = datetime.fromtimestamp(0, tz=timezone.utc)
    db_session = auth_domian.Session(session_id=session_id,
                                       start_time=epoch_start,
                                       end_time=expires,
                                       user=user, authorizations=authorizations)
    logger.debug('loaded user %s', user_id)
    db_session.ip_address = _ip_address()
    return db_session, token
    
def request_auth():
    """For use with `@app.before_reqeust()` to add `auth` attributes to `request`.

    Must be run inside a flask request context."""
    tokens = _get_cookies(request.environ) + _get_auth_bearer(request.environ)
    session, jwt_orig = None, None
    try:
        try:
            session, jwt_orig = _modern_auth(tokens)
        except ValidationError as ve: # nested try/except is intentional
            logger.debug(ve)
            session, jwt_orig = _ng_dict_jwt_auth(tokens)
    # same except handling for both _modern_auth and _ng_dict_jwt_auth
    except MissingToken:
        raise Unauthorized("no token or cookie")
    except InvalidToken:
        raise Unauthorized("no invalid token or cookie")
    except SessionCreationFailed:
        raise Unauthorized("no session or user")
    except ExpiredToken:
        raise Unauthorized("expired")

    if session:
        setattr(request,"auth", session)
        request.environ['token'] = jwt_orig
    else:
        raise Unauthorized("Authorization failed.")


def get_endorsements(user: auth_domian.User) -> list[str]:
    return [cat.id for cat in explicit_endorsements(user)]


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
    if not (session.user and session.user.user_id and session.user.profile and session.authorizations):
        # TODO: fix this to handle SA or other non user clients
        raise Unauthorized()

    name = " ".join([session.user.name.forename, session.user.name.surname]) if session.user.name \
        else "un-named user"

    if is_admin(session):
        user = StaffUser(
            user_id=session.user.user_id,
            name=name,
            email=session.user.email,
            endorsements = get_endorsements(session.user),
            scopes = session.authorizations.scopes,
        )
    else:
        user = PublicUser(
            user_id=session.user.user_id,
            name=name,
            email=session.user.email,
            endorsements = get_endorsements(session.user),
            scopes = session.authorizations.scopes,)

    ua = request.headers.get("User-Agent", "") if has_request_context() \
        else "BogusTestingUa"
    lang = request.headers.get("Accept-Language","none") if has_request_context() \
        else "da, en-gb;q=0.8, en;q=0.7"
    client = HttpClient(
        remote_addr= session.ip_address,
        remote_host= session.remote_host,
        device_type=get_device_type(ua),
        language=lang.split(",")[0][:4],)

    return user, client


def is_owner(session: auth_domian.Session, submission_id: str, **kw) -> bool:
    """Check whether the user has privileges to edit a submission."""
    submission, _ = backend.get_submission(int(submission_id))
    if not submission:
        raise NotFound('No such submission')
    logger.debug('Submission owned by %s; request is from %s',
                 submission.owner.identifier,
                 session.user.user_id)
    return str(submission.owner.user_id) == str(session.user.user_id)
