import os

from fastapi import FastAPI
from submit_ce.fastapi.api.default_api import router as DefaultApiRouter
from .config import config, DEV_SQLITE_FILE
from arxiv.config import settings


app = FastAPI(
    title="arxiv submit",
    description="No description provided (generated by Openapi Generator https://github.com/openapitools/openapi-generator)",
    version="0.1",
)
app.state.config = config

if not os.environ.get("CLASSIC_DB_URI", None):
    settings.CLASSIC_DB_URI = f"sqlite:///{DEV_SQLITE_FILE}"

config.submission_api_implementation.setup_fn(config)
app.include_router(DefaultApiRouter)
