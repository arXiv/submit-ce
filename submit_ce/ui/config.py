import os

from arxiv.config import Settings as ArxivBaseSettings
import openapi_client

from openapi_client.configuration import Configuration as APIConfiguration

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
                combined_dict[env_key] = value

        self.api_config = APIConfiguration(**combined_dict)

    api_config: APIConfiguration = APIConfiguration()
    AUTH_UPDATED_SESSION_REF: bool=True
    """Setting related to auth to force it to use 'auth' for the location of the user session instead of
    'session' which ususlaly has the flask session. This should always be 1 and in the future the setting should
    be removed from arxiv-base auth."""


settings = Settings()

