from arxiv.db import Session
from flask import current_app, has_app_context

from . import LegacySubmitImplementation
from sqlalchemy.orm import Session as SqlalchemySession

from submit_ce.domain.size_limits import SizeLimits, DEFAULT_MAX_SIZE_KB
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

    def get_size_limits(self) -> SizeLimits:
        """Build size limits from the configured ``MAX_*_KB`` values."""
        if not has_app_context():
            return SizeLimits.defaults()
        cfg = current_app.config
        return SizeLimits.from_kb(
            cfg.get("MAX_UNCOMPRESSED_TOTAL_KB", DEFAULT_MAX_SIZE_KB),
            cfg.get("MAX_UNCOMPRESSED_PER_FILE_KB", DEFAULT_MAX_SIZE_KB),
            cfg.get("MAX_COMPRESSED_KB", DEFAULT_MAX_SIZE_KB),
        )
