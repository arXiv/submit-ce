from typing import Optional

from fastapi import HTTPException, status


from submit_ce.domain.agent import Agent


async def get_user() -> Optional[Agent]:
    # TODO some kind of implementation
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
