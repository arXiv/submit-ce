import os

from fastapi import FastAPI
from submit_ce.fastapi.routes import router
from .config import config

app = FastAPI(
    title="arXiv submit",
    description="API to submit papers to arXiv.",
    version="0.1",
)
app.state.config = config

#config.submission_api_implementation.setup_fn(config)
app.include_router(router)
