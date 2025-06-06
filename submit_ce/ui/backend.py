"""Core persistence methods for submissions and submission events."""
from typing import Tuple, List, cast

from arxiv.db import Session, session_factory, configure_db
from flask import request, g, has_app_context
from werkzeug.exceptions import Unauthorized, BadRequest, NotFound

from submit_ce.api import SubmitApi, Submission, Event
from submit_ce.api.domain import User, Client
from submit_ce.api.exceptions import NoSuchSubmission
from submit_ce.implementations.legacy_implementation.flask_impl import FlaskSubmitImplementation


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

    if "submission" in g and "events" in g:
        if isinstance(g.submission, Submission) and isinstance(g.event, List):
            return g.submission, cast(List[Event], g.events)
    try:
        submission, history = api.get_with_history(submission_id)
        g.submission = submission
        g.events = history
        if isinstance(g.submission, Submission) and isinstance(g.events, List):
            return g.submission, cast(List[Event], g.events)
    except NoSuchSubmission as nss:
        raise NotFound()




def get_user() -> User:
    session = request.environ['auth']  # was already setup by arxiv.auth.auth.middleware
    if session is None:
        raise Unauthorized()

    return User(
        identifier=session.user.user_id,
        forename=session.user.name.forename,
        surname=session.user.name.surname,
        suffix=session.user.name.suffix,
        email=session.user.email,
        affiliation=session.user.profile.affiliation,
        endorsements=[],  # TODO where are endorsements other than the db? are they submission groups in the jwt?
        agent_type="User",
    )


def get_client() -> Client:
    ua = request.headers.get("User-Agent", None)
    if ua is None:
        agent_type = "ua-not-set"
    if ua.lower().startswith("mozilla"):
        agent_type = "browser"
    else:
        agent_type = ua[:20]

    # TODO hostname
    return Client(
        remoteAddress=request.remote_addr,
        remoteHost="",
        agent_type=agent_type,
        # agent_version="v223432"
    )


def endorsed_for(session: Session, category: str) -> bool:
    """
    Check whether category is included in this endorsement authorization.

    If a user/client is authorized for all categories in a particular
    archive, the category names in :attr:`Authorization.endorsements` will
    be compressed to a wilcard ``archive.*`` representation. If the
    user/client is authorized for all categories in the system, this will
    be compressed to "*.*".

    Parameters
    ----------
    category : str

    Returns
    -------
    bool

    """
    # TODO implement endorsed_for, maybe add to api? maybe move to arixv-base arxiv.auth Session?
    return True
    # archive = category.split(".", 1)[0] if "." in category else category
    # return category in session.endorsements \
    #     or f"{archive}.*" in session.endorsements \
    #     or "*.*" in session.endorsements

