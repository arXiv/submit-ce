from arxiv.db import Session

from . import LegacySubmitImplementation
from sqlalchemy.orm import Session as SqlalchemySession

from submit_ce.implementations.compile.compile_api_service import CompileApiService

def flask_get_session() -> SqlalchemySession:
    """Gets a SQLAlchemy session based on `arxiv.db.Session` which supports flask."""
    return Session()


class FlaskSubmitImplementation(LegacySubmitImplementation):
    """Implementation of the `SubmitApi` usable with flask."""

    def __init__(self,
                 store,
                 compiler=None,
                 email_service=None,
                 config=None,
    ):
        from submit_ce.domain.config import SubmitConfig
        from submit_ce.implementations import NullEmailService
        super().__init__(
            store=store,
            compiler=compiler or CompileApiService(),
            email_service=email_service or NullEmailService(),
            config=config or SubmitConfig(),
            get_session=flask_get_session,
        )
