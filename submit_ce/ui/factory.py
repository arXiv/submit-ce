import logging
from pathlib import Path
from typing import Optional

from flask.logging import default_handler
from flask import Flask, request

from arxiv.base import Base
from arxiv.config import settings as base_settings
from arxiv import db

from submit_ce.implementations.wiring import config_backend_api

from .auth import request_auth
from .config import settings
from . import filters
from .routes.paper_id_ui import PAPER_ID_UI
from .routes.ui import UI


base_settings.CLASSIC_DB_URI = settings.CLASSIC_DB_URI

root = logging.getLogger()
root.addHandler(default_handler)
root.setLevel(logging.INFO)

def create_web_app(config: Optional[dict]=None) -> Flask:
    """Initialize an instance of the search frontend UI web application."""
    app = Flask('submit',
                static_folder=Path(__file__).parent / 'static',
                template_folder=Path(__file__).parent / 'templates'
                )
    app.url_map.strict_slashes = False

    app.config.from_object(settings)

    app.config['TEMPLATES_AUTO_RELOAD']=True

    app.api = config_backend_api(settings)

    db.init(settings)
    Base(app)
    app.register_blueprint(UI)
    app.register_blueprint(PAPER_ID_UI)

    app.jinja_env.add_extension('jinja2.ext.do')
    for filter_name, filter_func in filters.get_filters():
        app.jinja_env.filters[filter_name] = filter_func
    app.jinja_env.globals['svgpaths']={}# will be loaded by ui/templates/svg.html

    app.config['CLASSIC_DB_URI'] = settings.CLASSIC_DB_URI
    app.config['CLASSIC_SESSION_HASH'] = settings.JWT_SECRET  # shove this in for arxiv-base use
    app.config['SESSION_DURATION']=7200 # to appease arxiv-base, not really used
    @app.before_request
    def check_auth():
        if request.path.startswith("/static") or request.path == "/status":
            return
        elif settings.LOCAL_LOGIN and request.path in ("/debug/login", "/debug/logout"):
            # Dev-only login/logout routes manage the session cookie, so they
            # must be reachable without a valid session. See routes.ui.
            return
        else:
            request_auth()

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        db.Session.remove()

    return app
