"""Core persistence methods for submissions and submission events."""

from typing import Tuple, List, cast

from arxiv.config import Settings
from arxiv.db import session_factory, configure_db
from flask import g, has_app_context, current_app
from werkzeug.exceptions import BadRequest, NotFound

from submit_ce.api import SubmitApi
from submit_ce.domain import User, Submission, Event
from submit_ce.domain.exceptions import NoSuchSubmission
from submit_ce.implementations.compile.compile_api_service import CompileApiService
from submit_ce.implementations.file_store.gs_file_store import GsFileStore
from submit_ce.implementations.legacy_implementation.flask_impl import FlaskSubmitImplementation
from submit_ce.implementations import NullFileStore

import logging
logger = logging.getLogger(__name__)

def config_backend_api(settings: Settings) -> SubmitApi:
    engine, _ = configure_db(settings)
    session_factory.configure(bind=engine)

    if settings.STORE == "gs":
        logger.info(f"Doing FileStore GS bucket {settings.STORE_GS_BUCKET} prefix {settings.STORE_GS_PREFIX}")
        store = GsFileStore(gs_bucket=settings.STORE_GS_BUCKET,
                            gs_prefix=settings.STORE_GS_PREFIX)
    elif settings.STORE == "null":
        store = NullFileStore()
    else:
        raise NotImplementedError("settings.store may not be set correctly.")
    return FlaskSubmitImplementation(
        store=store,
        compiler=CompileApiService())


def get_submission(submission_id: str) -> Tuple[Submission, List[Event]]:
    """
    Load a submission by ID.

    Parameters
    ----------
    submission_id : str

    Returns
    -------
    :class:`events.domain.Submission`

    Raises
    ------
    :class:`werkzeug.exceptions.NotFound`
        Raised when there is no submission with the specified ID.

    """
    if submission_id is None:
        raise BadRequest('No submission id')

    if not has_app_context():  # for testing to avoid problems with flask app context
        return current_app.api.get_with_history(submission_id)

    if "submission" in g and "events" in g and g.submission is not None and g.events is not None:        
        return (cast(Submission, g.submission), cast(List[Event], g.events))
    try:
        submission, history = current_app.api.get_with_history(submission_id)
        g.submission = submission
        g.events = history        
        return submission, history

    except NoSuchSubmission:
        raise NotFound()



def endorsed_for(user: User, category: str) -> bool:
    """
    Check whether category is included in `User`'s endorsement authorization.

    If a user/client is authorized for all categories in a particular
    archive, the category names in :attr:`Authorization.endorsements` will
    be compressed to a wildcard ``archive.*`` representation. If the
    user/client is authorized for all categories in the system, this will
    be compressed to "*.*".

    Parameters
    ----------
    user : user to check endorsements for.
    category : str of a category name
       Check if it is included in this endorsement authorizations.

    Returns
    -------
    bool

    """
    endorsements = getattr(user, 'endorsements', [])
    if not endorsements:
        return False

    archive = category.split(".", 1)[0] if "." in category else category
    return category in endorsements \
        or f"{archive}.*" in endorsements \
        or "*.*" in endorsements


def backend_startup_health_check():
    """Raises error if backend is not healthy."""
    if not current_app.api:
        raise RuntimeError("Flask current_app has no api")
    errors=[]
    if not current_app.api.get_file_store():
        errors.append("API lacks filestore")
    elif not current_app.api.get_file_store().is_available():
        errors.append("Filestore service is misconfigured or not available")
    if not current_app.api.get_compiler():
        errors.append("API lacks compiler")
    elif not current_app.api.get_compiler().is_available():
        errors.append("Compiler serivce is misconfigured or not available")

    if errors:
        raise RuntimeError(", ".join(errors))
