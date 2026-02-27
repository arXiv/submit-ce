"""Core persistence methods for submissions and submission events."""
from typing import Tuple, List, cast

from arxiv.config import Settings
from arxiv.db import session_factory, configure_db
from flask import g, has_app_context, current_app
from werkzeug.exceptions import BadRequest, NotFound

from submit_ce.api import SubmitApi, Submission, Event
from submit_ce.api.domain import User
from submit_ce.api.exceptions import NoSuchSubmission
from submit_ce.implementations.compile.compile_at_gcp_service import GcpCompileAtLegacy
from submit_ce.implementations.file_store.gs_file_store import GsFileStore
from submit_ce.implementations.file_store.legacy_file_store import LegacyFileStore
from submit_ce.implementations.legacy_implementation.flask_impl import FlaskSubmitImplementation


def config_backend_api(settings: Settings) -> SubmitApi:
    engine, _ = configure_db(settings)
    session_factory.configure(bind=engine)
    if settings.STORE == "gs":
        store = GsFileStore(gs_bucket=settings.STORE_GS_BUCKET,
                            gs_prefix=settings.STORE_GS_PREFIX)
    else:
        store = LegacyFileStore(root_dir=settings.STORE_LOCAL_ROOT)
    
    return FlaskSubmitImplementation(
        store=store,
        compiler=GcpCompileAtLegacy("data/new"))  # TODO compiler needs to know about store


def get_submission(submission_id: int) -> Tuple[Submission, List[Event]]:
    """
    Load a submission by ID.

    Parameters
    ----------
    submission_id : int

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



