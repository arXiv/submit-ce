from flask import Blueprint, render_template

blueprint = Blueprint('submit', __name__)

@blueprint.route('/', methods=["GET"])
# @auth.decorators.scoped(auth.scopes.CREATE_SUBMISSION,
#                         unauthorized=redirect_to_login)
def manage_submissions():
    """Display the ui-app management dashboard."""
    #return handle(cntrls.create, 'submit/manage_submissions.html',
    #              'Manage submissions')
    return render_template("submit/manage_submissions.html"
                           )#submit/manage_submissions.html")
#
# @blueprint.get("/")
# def home():
#     """
#     Home page, shows users submissions.
#
#     Redirects to login if not logged in.
#     """
#     return render_template("submit/manage_submissions.html"), 200, {}
