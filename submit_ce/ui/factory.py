import os
import pathlib
from typing import Optional

from arxiv.auth import auth
from arxiv.auth.auth.middleware import AuthMiddleware
from arxiv.base import Base, filters
from arxiv.base.middleware import wrap
from flask import Flask

from .router import router
from .config import Settings, DEV_SQLITE_FILE

def create_web_app(config: Optional[dict]=None) -> Flask:
    """Initialize an instance of the search frontend UI web application."""
    app = Flask('submit', static_folder='static', template_folder='templates')
    app.url_map.strict_slashes = False

    settings = Settings(**config or {})
    app.config.from_object(settings)

    Base(app)
    auth.Auth(app)
    app.register_blueprint(ui)
    middleware = [AuthMiddleware]
    wrap(app, middleware)

    for filter_name, filter_func in filters.get_filters():
        app.jinja_env.filters[filter_name] = filter_func

    return app
