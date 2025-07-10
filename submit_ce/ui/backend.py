"""Core persistence methods for submissions and submission events."""
from typing import Optional, Tuple, List, cast

from arxiv.auth.domain import Session
from arxiv.db import session_factory, configure_db
from flask import request, g, has_app_context
from werkzeug.exceptions import Unauthorized, BadRequest, NotFound

from submit_ce.api import SubmitApi, Submission, Event, User, Client, PublicUser, StaffUser, HttpClient
from submit_ce.api.domain import User, Client
from submit_ce.api.domain.agent import HttpClient, PublicUser
from submit_ce.api.exceptions import NoSuchSubmission
from submit_ce.implementations.legacy_implementation.flask_impl import FlaskSubmitImplementation
from submit_ce.ui.auth import _public_user


def config_backend_api(settings)-> None:
    engine, _ = configure_db(settings)
    session_factory.configure(bind=engine)


api: SubmitApi = FlaskSubmitImplementation()
"""Backend forced to be legacy implementation just for testing. It should be configurable via Settings."""


def get_submission(submission_id: int) -> Tuple[Submission, List[Event]]:
    """
    Load a submission by ID.

    Parameters
    ----------
    submission_id : int

    Returns
    -------
    :class:`events.domain.Submission`

    Raises
    ------
    :class:`werkzeug.exceptions.NotFound`
        Raised when there is no submission with the specified ID.

    """
    if submission_id is None:
        raise BadRequest('No submission id')

    if not has_app_context():  # for testing to avoid problems with flask app context
        return api.get_with_history(submission_id)

    if "submission" in g and "events" in g and g.submission is not None and g.events is not None:        
        return (cast(Submission, g.submission), cast(List[Event], g.events))
    try:
        submission, history = api.get_with_history(submission_id)
        g.submission = submission
        g.events = history        
        return submission, history

    except NoSuchSubmission as nss:
        raise NotFound()


def endorsed_for(user: User, category: str) -> bool:
    """
    Check whether category is included in `User`'s endorsement authorization.

    If a user/client is authorized for all categories in a particular
    archive, the category names in :attr:`Authorization.endorsements` will
    be compressed to a wildcard ``archive.*`` representation. If the
    user/client is authorized for all categories in the system, this will
    be compressed to "*.*".

    Parameters
    ----------
    category : str of a category name
       Check if it is included in this endorsement authorizations.

    Returns
    -------
    bool

    """
    endorsements = getattr(user, 'endorsements', [])
    if not endorsements:
        return False

    archive = category.split(".", 1)[0] if "." in category else category
    return category in endorsements \
        or f"{archive}.*" in endorsements \
        or "*.*" in endorsements


def _get_user(session: Optional[Session]=None) -> User:
    if not session:
        session = request.environ['auth']  # was already setup by arxiv.auth.auth.middleware

    if not(session and session.user and session.user.user_id and session.authorizations):
        raise Unauthorized()    

    if session.user.name:
        name = " ".join([session.user.name.forename, session.user.name.surname])
    else:
        name = "un-named user"

    if hasattr(session.authorizations, 'endorsements'):
        endorsements = session.authorizations.endorsements
    else:
        endorsements = []  # todo what to do?

    # TODO handle staff users
    return PublicUser(
        user_id=session.user.user_id,
        name=name,
        email=session.user.email,            
        endorsements = endorsements,
        scopes = session.authorizations.scopes,
    )


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
