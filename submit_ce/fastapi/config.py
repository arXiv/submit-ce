import secrets

from pydantic_settings import BaseSettings

from pydantic import SecretStr, ImportString

DEV_SQLITE_FILE="legacy.db"

class Settings(BaseSettings):
    """CLASSIC_DB_URI and other configs are from arxiv-base arxiv.config."""


    submission_api_implementation: ImportString = 'submit_ce.fastapi.implementations.legacy_implementation.implementation'
    """Class to use for submission API implementation."""


config = Settings(_case_sensitive=False)
"""Settings build from defaults, env file, and env vars.

Environment vars have the highest precedence, defaults the lowest."""
