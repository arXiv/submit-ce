from dataclasses import dataclass
from typing import Callable

from pydantic_settings import BaseSettings

from submit_ce.api.implementations.default_api_base import BaseDefaultApi


@dataclass
class ImplementationConfig:
    impl: BaseDefaultApi
    depends_fn: Callable
    setup_fn: Callable[[BaseSettings], None]
