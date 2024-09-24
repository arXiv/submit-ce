import pathlib

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from submit_ce.auth import get_client, get_user

router = APIRouter(
    #response_class=HTMLResponse
)

templates = Jinja2Templates(directory=pathlib.Path(__file__).parent.resolve()/"templates")

@router.get("/")
async def home(request: Request, user=get_user, client=get_client):
    """
    Home page, shows users submissions.

    Redirects to login if not logged in.
    """
    return templates.TemplateResponse(request=request,
        name="home.html",
        context={"id": id}
    )
