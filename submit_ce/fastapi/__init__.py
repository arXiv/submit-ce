from dataclasses import dataclass
from typing import Callable

from pydantic_settings import BaseSettings
from starlette.requests import Request

from submit_ce.api.core import CoreSubmitApi
from submit_ce.api.domain import User


@dataclass
class ImplementationConfig:
    impl: CoreSubmitApi
    depends_fn: Callable
    setup_fn: Callable[[BaseSettings], None]
    userid_to_user: Callable[[Request, str], User]


