from typing import Optional

from arxiv.auth.auth.tokens import decode
from flask import Request

from submit_ce.api.domain import User

def get_user_impl(request: Request, token: str) -> Optional[User]:
    secret = request.app.state.config.jwt_secret
    session = decode(token, secret)
    return User(
        identifier=session.user.user_id,
        forename=session.user.name.forename,
        surname=session.user.name.surname,
        suffix=session.user.name.suffix,
        email=session.user.email,
        affiliation=session.user.profile.affiliation,
        endorsements=[], # TODO where are endorsements other than the db? submission groups?
        agent_type="User",
    )
