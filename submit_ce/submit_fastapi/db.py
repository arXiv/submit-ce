from fastapi import Depends
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_sessionLocal = sessionmaker(autocommit=False, autoflush=False)


def get_sessionlocal():
    global _sessionLocal
    if _sessionLocal is None:
        from .config import config
        if 'sqlite' in config.classic_db_uri:
            args = {"check_same_thread": False}
        else:
            args = {}
        engine = create_engine(config.classic_db_uri, echo=config.echo_sql, connect_args=args)
        _sessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    return _sessionLocal


def get_db(session_local=Depends(get_sessionlocal)):
    """Dependency for fastapi routes"""
    with session_local() as session:
        try:
            yield session
            if session.begin or session.dirty or session.deleted:
                session.commit()
        except Exception:
            session.rollback()
            raise

