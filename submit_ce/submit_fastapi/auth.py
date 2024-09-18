import uuid
from typing import Optional

from fastapi import HTTPException, status, Request


from submit_ce.submit_fastapi.api.models.agent import User, Client


async def get_client(request: Request) -> Client:
    # TODO some kind of implementation

    ua = request.headers.get("User-Agent", None)
    if ua is None:
        agent_type="ua-not-set"
    if ua.lower().startswith("mozilla"):
        agent_type="browser"
    else:
        agent_type=ua[:20]

    # todo hostname

    return Client(
        remoteAddress=request.client.host,
        remoteHost="",
        agent_type=agent_type,
        # agent_version="v223432"
    )


async def get_user() -> Optional[User]:
    # TODO some kind of implementation
    #raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return User(identifier="bobsmith",

                forename="Bob",
                suffix="Sr",
                surname="SURn",

                affiliation=str(uuid.uuid4()),
                email="bob@example.com",
                endorsements=[]
                )
