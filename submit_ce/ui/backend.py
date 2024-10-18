"""Core persistence methods for submissions and submission events."""
import logging
from typing import List, Tuple, Optional

from arxiv.db import Session, session_factory, configure_db
from flask import request
from werkzeug.exceptions import Unauthorized

from submit_ce.api import SubmitApi
from submit_ce.api.domain import Submission
from submit_ce.api.domain import User, Client
from submit_ce.api.domain.event import Event
from submit_ce.implementations.legacy_implementation.flask_impl import FlaskSubmitImplementation

def config_backend_api(settings)-> None:
    engine, _ = configure_db(settings)
    session_factory.configure(
        bind=engine,
    #     binds={
    #     models.Base: engine,
    # },
    )


api: SubmitApi = FlaskSubmitImplementation()
"""Backend forced to be legacy implementation just for testing. It should be configurable via Settings."""


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

    # todo hostname
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

