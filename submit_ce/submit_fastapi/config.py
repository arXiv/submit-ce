import secrets

from pydantic_settings import BaseSettings

from pydantic import SecretStr, ImportString


class Settings(BaseSettings):
    classic_db_uri: str = 'sqlite://legacy.db'
    """arXiv legacy DB URL."""

    jwt_secret: SecretStr = "not-set-" + secrets.token_urlsafe(16)
    """NG JWT_SECRET from arxiv-auth login service"""

    submission_api_implementation: ImportString = 'submit_ce.submit_fastapi.implementations.legacy_implementation.implementation'
    """Class to use for submission API implementation."""


config = Settings(_case_sensitive=False)
"""Settings build from defaults, env file, and env vars.

Environment vars have the highest precedence, defaults the lowest."""
