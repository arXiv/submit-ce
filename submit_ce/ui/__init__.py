import os
import pathlib

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .router import router
from .config import settings, DEV_SQLITE_FILE


app = FastAPI(
    title="arXiv UI",
    description="UI to submit papers to arXiv.",
    version="0.1",
)
app.state.config = settings

if not os.environ.get("CLASSIC_DB_URI", None):
    settings.CLASSIC_DB_URI = f"sqlite:///{DEV_SQLITE_FILE}"

app.include_router(router)
app.mount("/static",
    StaticFiles(directory=pathlib.Path(__file__).parent.resolve()/"static"),
          name="static",
          )
