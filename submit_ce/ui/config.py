import os

from arxiv.config import settings as arxivbase_settings, Settings as ArxivBaseSettings
from pydantic import ImportString

DEV_SQLITE_FILE="legacy.db"

SUBMIT_API_CONFIG_PREFIX="SUBMIT_API_"
"""Env vars starting with this will configure the submit api client."""



class Settings(ArxivBaseSettings):
    def __init__(self, **kwargs):
        super().__init__(kwargs)

        # gets all SUBMIT_API_ env vars and tries to make them into configs
        combined_dict = kwargs.copy()
        for key, value in os.environ.items():
            if key.startswith(SUBMIT_API_CONFIG_PREFIX):
                env_key = key[len(SUBMIT_API_CONFIG_PREFIX):]  # Remove prefix
                combined_dict[env_key.lower()] = value
        if "host" not in combined_dict:
            combined_dict["host"] = "http://localhost:8000"

        self.api_config = combined_dict

        if "CLASSIC_DB_URI" not in os.environ:
            self.CLASSIC_DB_URI = f"sqlite:///{DEV_SQLITE_FILE}"

    api_config: dict = {}
    """Configuration to submit backend API. 
     
     Can be set with envvars that are prefixed with SUBMIT_API_{SOMETHING}.
     Ex. SUBMIT_API_HOST=http://localhost:8000"""

    submission_api_implementation: ImportString = 'submit_ce.api.implementations.legacy_implementation.implementation'
    """Class to use for submission API implementation."""

    AUTH_UPDATED_SESSION_REF: bool = True
    """Setting related to auth to force it to use 'auth' for the location of the user session instead of
    'session' which usually has the flask session. This should always be 1 and in the future the setting should
    be removed from arxiv-base auth."""

    CSRF_SESSION_KEY: str = ""
    """arxiv-base CSRF key, should be replaced with just normal ue of wtforms."""
    CSRF_SECRET: str = "foobar"

    CLASSIC_DB_URI: str = f"sqlite:///{DEV_SQLITE_FILE}"

settings = Settings()
arxivbase_settings.CLASSIC_DB_URI = settings.CLASSIC_DB_URI


