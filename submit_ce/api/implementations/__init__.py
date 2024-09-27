from dataclasses import dataclass
from typing import Callable
from fastapi import Request
from pydantic_settings import BaseSettings

from submit_ce.api import domain
from submit_ce.api.implementations.default_api_base import BaseDefaultApi


@dataclass
class ImplementationConfig:
    impl: BaseDefaultApi
    depends_fn: Callable
    setup_fn: Callable[[BaseSettings], None]
    userid_to_user: Callable[[Request, str], domain.User]
