import uuid
from typing import Optional

from fastapi import HTTPException, status


from submit_ce.submit_fastapi.api.models.agent import Agent, User


async def get_user() -> Optional[Agent]:
    # TODO some kind of implementation
    #raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return User(native_id=str(uuid.uuid4()),
                name="Redundent?",
                first_name="Bob",
                last_name="Smith",
                surname="SURn",
                affiliation=str(uuid.uuid4()),
                username=str(uuid.uuid4()),
                email=str(uuid.uuid4()),
                endorsements=[]
                )