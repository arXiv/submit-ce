import logging
from pathlib import Path
from typing import Optional

from arxiv.auth import auth
from arxiv.auth.auth.middleware import AuthMiddleware
from arxiv.base import Base
from arxiv.base.middleware import wrap
from flask import Flask

from .config import settings
from arxiv.config import settings as base_settings
base_settings.CLASSIC_DB_URI = settings.CLASSIC_DB_URI
from . import filters, backend
from .routes.ui import UI

from flask.logging import default_handler
root = logging.getLogger()
root.addHandler(default_handler)

def create_web_app(config: Optional[dict]=None) -> Flask:
    """Initialize an instance of the search frontend UI web application."""


    app = Flask('submit',
                static_folder=Path(__file__).parent / 'static',
                template_folder=Path(__file__).parent / 'templates'
                )
    app.url_map.strict_slashes = False

    app.config.from_object(settings)
    backend.config_backend_api(settings)
    Base(app)
    auth.Auth(app)
    app.register_blueprint(UI)
    middleware = [AuthMiddleware]
    wrap(app, middleware)

    for filter_name, filter_func in filters.get_filters():
        app.jinja_env.filters[filter_name] = filter_func

    return app
