if __name__ == '__main__':
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
import fire
from submit_ce.api.config import DEV_SQLITE_FILE


def create_all_legacy_db(test_db_file: str=DEV_SQLITE_FILE, echo: bool=False):
    """Legacy db with all tables created but no data."""
    url = f"sqlite:///{test_db_file}"
    engine = create_engine(url, echo=echo)
    from arxiv.db.models import configure_db_engine
    configure_db_engine(engine, None)
    from arxiv.db import metadata
    with Session(engine) as session:
        import arxiv.db.models as models
        models.configure_db_engine(session.get_bind(), None)
        metadata.create_all(bind=engine)
        session.commit()

    return (engine, url, test_db_file)


if __name__ == "__main__":
    fire.Fire(create_all_legacy_db)
