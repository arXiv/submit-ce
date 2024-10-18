from arxiv.auth.domain import Session as AuthSession
from arxiv.db import Session
from flask import request

from . import LegacySubmitImplementation
from sqlalchemy.orm import Session as SqlalchemySession

from ...api.domain import Client, User


def flask_get_session() -> SqlalchemySession:
    """Gets a SQLAlchemy session based on `arxiv.db.Session` which supports flask."""
    return Session()


def flask_get_user() -> User:
    """Gets a `User` based on `arxiv.auth.auth.Auth` flask middleware."""
    session: AuthSession = request.auth
    return User(
        session.user.user_id,
        email=session.user.email,
        forename=getattr(session.user.name, 'forename', None),
        surname=getattr(session.user.name, 'surname', None),
        suffix=getattr(session.user.name, 'suffix', None),
        # todo from the legacy.db and jwt from tests/make_test_db.py I'm not getting endorsements
        #endorsements=session.authorizations.endorsements
        endorsements=[]
    )


def flask_get_client() -> Client:
    """Gets a `Client` based on flask `request`."""
    return Client(
        remoteAddress=request.remote_addr,
        remoteHost="",
        agent_type="TODO",
    )


class FlaskSubmitImplementation(LegacySubmitImplementation):
    """Implementation of the `SubmitApi` usable with flask."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.get_session = flask_get_session
        self.get_user = flask_get_user
        self.get_client = flask_get_client
