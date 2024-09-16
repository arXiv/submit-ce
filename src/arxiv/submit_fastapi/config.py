import secrets
from typing import List, Union

from pydantic_settings import BaseSettings

from pydantic import SecretStr, PyObject



class Settings(BaseSettings):
    classic_db_uri: str = 'mysql://not-set-check-config/0000'
    """arXiv legacy DB URL."""

    jwt_secret: SecretStr = "not-set-" + secrets.token_urlsafe(16)
    """NG JWT_SECRET from arxiv-auth login service"""

    submission_api_implementation: PyObject = 'arxiv.submit_fastapi.api.legacy_implementation.LegacySubmitImplementation'
    """Class to use for submission API implementation."""

    submission_api_implementation_depends_function: PyObject = 'arxiv.submit_fastapi.api.legacy_implementation.legacy_depends'
    """Function to depend on submission API implementation."""


    class Config:
        env_file = "env"
        """File to read environment from"""

        case_sensitive = False


config = Settings()
"""Settings build from defaults, env file, and env vars.

Environment vars have the highest precedence, defaults the lowest."""
