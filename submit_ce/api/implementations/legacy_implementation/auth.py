from typing import Optional

from arxiv.auth.auth.tokens import decode
from flask import Request
from pydantic import SecretStr

from submit_ce.api.domain import User

def get_user_impl(request: Request, token: str) -> Optional[User]:
    secret = request.app.state.config.jwt_secret
    if isinstance(secret, SecretStr):
        secret = secret.get_secret_value()

    session = decode(token, secret)
    return User(
        identifier=session.user.user_id,
        forename=session.user.name.forename,
        surname=session.user.name.surname,
        suffix=session.user.name.suffix,
        email=session.user.email,
        affiliation=session.user.profile.affiliation,
        endorsements=[], # TODO where are endorsements other than the db? are they submission groups in the jwt?
        agent_type="User",
    )
