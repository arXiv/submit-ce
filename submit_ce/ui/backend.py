"""Core persistence methods for submissions and submission events."""

from typing import Tuple, List, cast

from arxiv.config import Settings
from arxiv.db import session_factory, configure_db
from flask import g, has_app_context, current_app
from werkzeug.exceptions import BadRequest, NotFound

from submit_ce.api import SubmitApi
from submit_ce.domain import User, Submission, Event
from submit_ce.domain.exceptions import NoSuchSubmission
from submit_ce.domain.config import SubmitConfig
from submit_ce.implementations.compile.compile_api_service import CompileApiService
from submit_ce.implementations.email import HalonEmailService
from submit_ce.implementations.email.email_in_memory import EmailInMemory
from submit_ce.implementations.email.smtp_creds import smtp_creds_from_secret
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
                            gs_prefix=settings.STORE_GS_PREFIX,
                            qa_bucket=settings.QA_GS_BUCKET,
                            qa_prefix=settings.QA_GS_PREFIX)
    elif settings.STORE == "null":
        store = NullFileStore()
    else:
        raise NotImplementedError("settings.store may not be set correctly.")

    email_service = email_service_from_settings(settings)

    return FlaskSubmitImplementation(
        store=store,
        compiler=CompileApiService(),
        email_service=email_service,
        config=SubmitConfig.from_config(settings),
        # This is where SaveParticipants get wired into every save()
        # transaction. See submit_ce.api.save_participant.
        participants=[])


def email_service_from_settings(settings: Settings):
    """Build the configured `EmailService` from application settings.

    ``EMAIL_MODE`` selects the implementation: ``HALON`` builds a
    `HalonEmailService` that sends real mail; ``TESTING`` builds an
    `EmailInMemory` that captures messages instead of sending them.
    """
    if settings.EMAIL_MODE == "TESTING":
        logger.info("EMAIL_MODE=TESTING: using in-memory email service")
        return EmailInMemory()

    creds = smtp_creds_from_secret(settings.EMAIL_SMTP_SECRET)
    return HalonEmailService(
        host=creds.host,
        port=creds.port or 465,
        user=creds.user,
        password=creds.password,
        from_address=settings.EMAIL_FROM,
        use_starttls=creds.use_starttls,
        timeout=settings.EMAIL_TIMEOUT,
    )


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
        errors.append("Compiler service is misconfigured or not available")

    if errors:
        raise RuntimeError(", ".join(errors))
