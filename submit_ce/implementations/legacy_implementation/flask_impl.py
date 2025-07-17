from pathlib import Path
from arxiv.db import Session

from . import LegacySubmitImplementation
from sqlalchemy.orm import Session as SqlalchemySession

from ..compile.compile_at_gcp_service import GcpCompileAtLegacy
from ..file_store.legacy_file_store import LegacyFileStore


def flask_get_session() -> SqlalchemySession:
    """Gets a SQLAlchemy session based on `arxiv.db.Session` which supports flask."""
    return Session()


class FlaskSubmitImplementation(LegacySubmitImplementation):
    """Implementation of the `SubmitApi` usable with flask."""

    def __init__(self,
                 store,
                 compiler):
        # TODO this init is not good
        root_dir =  "data/new"
        store = store or LegacyFileStore(root_dir=Path(root_dir))
        compiler = compiler or GcpCompileAtLegacy(root_dir)
        super().__init__(store=store, compiler=compiler)
        self.get_session = flask_get_session
