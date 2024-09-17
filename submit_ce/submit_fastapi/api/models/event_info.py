# coding: utf-8

"""
    event info

    Basic information about an event.
"""  # noqa: E501


from __future__ import annotations
import re
from datetime import datetime

from pydantic import BaseModel


class EventInfo(BaseModel):
    event_id: str
    recorded: datetime
    submission_id: str
    user_id: str