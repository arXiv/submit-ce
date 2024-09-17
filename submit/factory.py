"""Application factory for references service components."""

import logging as pylogging
import time
from typing import Any, Optional

from arxiv_auth.auth.middleware import AuthMiddleware
from typing_extensions import Protocol
from flask import Flask

from arxiv.base import Base, logging
from arxiv_auth import auth
from arxiv.base.middleware import wrap, request_logs
from arxiv.submission.services import classic, Compiler, Filemanager
from arxiv.submission.domain.uploads import FileErrorLevels
from arxiv.submission import init_app

from .routes import UI
from . import filters


pylogging.getLogger('arxiv.ui-app.services.classic.interpolate') \
    .setLevel(10)
pylogging.getLogger('arxiv.ui-app.domain.event.event').setLevel(10)
logger = logging.getLogger(__name__)


def create_ui_web_app(config: Optional[dict]=None) -> Flask:
    """Initialize an instance of the search frontend UI web application."""
    app = Flask('submit', static_folder='static', template_folder='templates')
    app.url_map.strict_slashes = False
    app.config.from_pyfile('config.py')
    if config is not None:
        app.config.update(config)
    Base(app)
    auth.Auth(app)
    app.register_blueprint(UI)
    middleware = [request_logs.ClassicLogsMiddleware,
                  AuthMiddleware]
    wrap(app, middleware)

    # Make sure that we have all of the secrets that we need to run.
    if app.config['VAULT_ENABLED']:
        app.middlewares['VaultMiddleware'].update_secrets({})

    for filter_name, filter_func in filters.get_filters():
        app.jinja_env.filters[filter_name] = filter_func

    # Initialize services.

    # Initializes

    # The following stmt initializes
    # stream publisher at AWS (DEAD)
    # preview PDF service
    # legacy DB both normal submissions and a new events table
    init_app(app)

    Compiler.init_app(app)

    Filemanager.init_app(app)

    if app.config['WAIT_FOR_SERVICES']:
        time.sleep(app.config['WAIT_ON_STARTUP'])
        with app.app_context():
            wait_for(Filemanager.current_session(),
                     timeout=app.config['FILEMANAGER_STATUS_TIMEOUT'])
            wait_for(Compiler.current_session(),
                     timeout=app.config['COMPILER_STATUS_TIMEOUT'])
        logger.info('All upstream services are available; ready to start')

    app.jinja_env.globals['FileErrorLevels'] = FileErrorLevels

    return app


# This stuff may be worth moving to base; so far it has proven pretty
# ubiquitously helpful, and kind of makes sense in arxiv.integration.service.

class IAwaitable(Protocol):
    """An object that provides an ``is_available`` predicate."""

    def is_available(self, **kwargs: Any) -> bool:
        """Check whether an object (e.g. a service) is available."""
        ...


def wait_for(service: IAwaitable, delay: int = 2, **extra: Any) -> None:
    """Wait for a service to become available."""
    if hasattr(service, '__name__'):
        service_name = service.__name__    # type: ignore
    elif hasattr(service, '__class__'):
        service_name = service.__class__.__name__
    else:
        service_name = str(service)

    logger.info('await %s', service_name)
    while not service.is_available(**extra):
        logger.info('service %s is not available; try again', service_name)
        time.sleep(delay)
    logger.info('service %s is available!', service_name)
