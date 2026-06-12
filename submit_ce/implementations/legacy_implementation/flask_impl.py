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
                 compiler,
                 email_service=None,
    ):
        store = store
        compiler = compiler or CompileApiService()
        super().__init__(store=store, compiler=compiler,
                         email_service=email_service)
        self.get_session = flask_get_session
