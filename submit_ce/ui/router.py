from flask import Blueprint, render_template

blueprint = Blueprint('submit', __name__)

@blueprint.get("/")
async def home():
    """
    Home page, shows users submissions.

    Redirects to login if not logged in.
    """
    return render_template("submit/manage_submissions.html"), 200, {}
