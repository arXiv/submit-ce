"""Helpers and utilities."""

from datetime import datetime
from typing import Dict, Any, List, Callable, Iterable

from pytz import UTC


def get_tzaware_utc_now() -> datetime:
    """Generate a datetime for the current moment in UTC."""
    return datetime.now(UTC)


def dict_coerce(factory: Callable[..., Any], data: dict) -> Dict[str, Any]:
    return {event_id: factory(**value) if isinstance(value, dict) else value
            for event_id, value in data.items()}


def list_coerce(factory: type, data: Iterable) -> List[Any]:
    return [factory(**value) for value in data if isinstance(value, dict)]
