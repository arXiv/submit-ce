"""Build a configured `SubmitApi` from application settings.

This is framework-neutral on purpose: it imports no Flask and no FastAPI, so
both the Flask UI (`submit_ce.ui.factory`) and other front ends can construct
the same backend. It previously lived in `submit_ce.ui.backend`, which imports
Flask and therefore could not be used from a non-Flask process.
"""

import logging
from typing import Callable

from arxiv.config import Settings
from arxiv.db import session_factory, configure_db

from submit_ce.api import SubmitApi
from submit_ce.domain.config import SubmitConfig
from submit_ce.implementations import NullFileStore
from submit_ce.implementations.compile.compile_api_service import CompileApiService
from submit_ce.implementations.email import HalonEmailService
from submit_ce.implementations.email.email_in_memory import EmailInMemory
from submit_ce.implementations.email.smtp_creds import smtp_creds_from_secret
from submit_ce.implementations.file_store.gs_file_store import GsFileStore
from submit_ce.implementations.legacy_implementation.flask_impl import FlaskSubmitImplementation

logger = logging.getLogger(__name__)


def config_backend_api(settings: Settings,
                       impl: Callable[..., SubmitApi] = FlaskSubmitImplementation,
                       ) -> SubmitApi:
    """Build the `SubmitApi`.

    ``impl`` selects the implementation, which differs only in how it obtains a
    SQLAlchemy session. Defaults to the Flask-scoped one used by the UI; a
    non-Flask front end passes `FastapiSubmitImplementation`.
    """
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

    return impl(
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
