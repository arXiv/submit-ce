from dataclasses import dataclass
from typing import Callable
from fastapi import Request
from pydantic_settings import BaseSettings


@dataclass
class ImplementationConfig:
    impl: BaseDefaultApi
    depends_fn: Callable
    setup_fn: Callable[[BaseSettings], None]
    userid_to_user: Callable[[Request, str], domain.User]
