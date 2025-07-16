import logging
from pathlib import Path
from typing import Optional

from flask.logging import default_handler
from flask import Flask

from arxiv.base import Base
from arxiv.config import settings as base_settings
from arxiv import db

from .auth import setup_auth
from .config import settings
from . import backend, filters
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
    backend.config_backend_api(settings)
    db.init(settings)
    Base(app)
    app.register_blueprint(UI)

    for filter_name, filter_func in filters.get_filters():
        app.jinja_env.filters[filter_name] = filter_func


    app.config['CLASSIC_DB_URI'] = settings.CLASSIC_DB_URI
    app.config['CLASSIC_SESSION_HASH'] = settings.JWT_SECRET  # shove this in for arxiv-base use
    app.config['SESSION_DURATION']=7200 # to appease arxiv-base, not really used
    @app.before_request
    def check_auth():
        setup_auth()

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        db.Session.remove()

    return app
