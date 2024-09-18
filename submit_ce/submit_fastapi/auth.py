import uuid
from typing import Optional

from fastapi import HTTPException, status


from submit_ce.submit_fastapi.api.models.agent import User, Client


async def get_client() -> Client:
    # TODO some kind of implementation
    return Client(
        remoteAddress="127.0.0.1",
        remoteHost="example.com",
        agent_type="browser",
        agent_version="v223432"
    )

async def get_user() -> Optional[User]:
    # TODO some kind of implementation
    #raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return User(native_id=str(uuid.uuid4()),
                name="Redundent?",
                first_name="Bob",
                forename="Bob",
                suffix="Sr",
                last_name="Smith",
                surname="SURn",
                affiliation=str(uuid.uuid4()),
                username=str(uuid.uuid4()),
                email=str(uuid.uuid4()),
                endorsements=[]
                )
