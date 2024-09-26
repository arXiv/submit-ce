"""Bootstraps users and other DB entities for testing/dev.

This script will wait for the DB to become available and then
check if the arXiv_submissions table exists.

If the table doesn't exist, this script will create all the legacy tables and
create several testing users, and print JWTs for those user.

If the table exists it will do nothing.

If run with the flag --output-single-jwt it will always output a
single JWT to stdout.

This can be used like:

    python tests/make_tests_db.py --output-single-jwt > jwt.txt
    INTEGRATION_JWT = $(cat jwt.txt) python -m submit.integration.test_integration

Testing and debugging this script outside of docker can be done like:

   JWT_SECRET='X' CLASSIC_DATABASE_URI='sqlite:///tmpbootstrap.db.sqlite' python tests/make_tests_db.py

Then you can run it again, and it will find the existing db.
"""
import os

from arxiv.auth.auth.middleware import AuthMiddleware
from arxiv.base import Base
from arxiv.config import Settings
from arxiv.taxonomy.definitions import CATEGORIES
from flask import Flask
from sqlalchemy.orm import Session

if __name__ == '__main__':
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text
import fire
from submit_ce.api.config import DEV_SQLITE_FILE

import time
import logging

from arxiv.auth.auth import scopes
from arxiv.auth.helpers import generate_token
from arxiv.db import models

# from arxiv.users.helpers import generate_token
# from arxiv.users.auth import scopes

import random
from datetime import datetime
from typing import List, Dict, Any, Optional

from mimesis import Person, Internet, Datetime
from mimesis.locales import Locale

from arxiv import taxonomy
from arxiv.auth import auth

# The logging in NG is a bit much, tone it down
logging.basicConfig()
logging.getLogger("arxiv.submission.services.classic.interpolate").setLevel(logging.ERROR)
logging.getLogger("arxiv.base.alerts").setLevel(logging.ERROR)
logging.getLogger("arxiv.vault.middleware").setLevel(logging.CRITICAL)

logger = logging.getLogger(__file__)
logger.setLevel(logging.DEBUG)


LOCALES = list(Locale)

def _get_locale() -> str:
    loc: str = LOCALES[random.randint(0, len(LOCALES) - 1)]
    return loc


def _epoch(t: datetime) -> int:
    return int((t - datetime.utcfromtimestamp(0)).total_seconds())


LICENSES: List[Dict[str, Any]] = [
    {
        "name": "",
        "note": None,
        "label": "None of the above licenses apply",
        "active": 1,
        "sequence": 99
    },
    {
        "name": "http://arxiv.org/licenses/assumed-1991-2003/",
        "note": "",
        "label": "Assumed arXiv.org perpetual, non-exclusive license to" +
                 " distribute this article for submissions made before" +
                 " January 2004",
        "active": 0,
        "sequence": 9
    },
    {
        "name": "http://arxiv.org/licenses/nonexclusive-distrib/1.0/",
        "note": "(Minimal rights required by arXiv.org. Select this unless" +
                " you understand the implications of other licenses.)",
        "label": "arXiv.org perpetual, non-exclusive license to distribute" +
                 " this article",
        "active": 1,
        "sequence": 1
    },
    {
        "name": "http://creativecommons.org/licenses/by-nc-sa/3.0/",
        "note": "",
        "label": "Creative Commons Attribution-Noncommercial-ShareAlike" +
                 " license",
        "active": 0,
        "sequence": 3
    },
    {
        "name": "http://creativecommons.org/licenses/by-nc-sa/4.0/",
        "note": "",
        "label": "Creative Commons Attribution-Noncommercial-ShareAlike" +
                 " license (CC BY-NC-SA 4.0)",
        "active": 1,
        "sequence": 7
    },
    {
        "name": "http://creativecommons.org/licenses/by-sa/4.0/",
        "note": "",
        "label": "Creative Commons Attribution-ShareAlike license" +
                 " (CC BY-SA 4.0)",
        "active": 1,
        "sequence": 6
    },
    {
        "name": "http://creativecommons.org/licenses/by/3.0/",
        "note": "",
        "label": "Creative Commons Attribution license",
        "active": 0,
        "sequence": 2
    },
    {
        "name": "http://creativecommons.org/licenses/by/4.0/",
        "note": "",
        "label": "Creative Commons Attribution license (CC BY 4.0)",
        "active": 1,
        "sequence": 5
    },
    {
        "name": "http://creativecommons.org/licenses/publicdomain/",
        "note": "(Suitable for US government employees, for example)",
        "label": "Creative Commons Public Domain Declaration",
        "active": 0,
        "sequence": 4
    },
    {
        "name": "http://creativecommons.org/publicdomain/zero/1.0/",
        "note": "",
        "label": "Creative Commons Public Domain Declaration (CC0 1.0)",
        "active": 1,
        "sequence": 8
    }
]

POLICY_CLASSES = [
    {"name": "Administrator", "class_id": 1, "description": "", "password_storage":2, "recovery_policy":3, "permanent_login":1},
    {"name": "Public user", "class_id": 2, "description": "", "password_storage":2, "recovery_policy":3, "permanent_login":1},
    {"name": "Legacy user", "class_id": 3, "description": "", "password_storage":2, "recovery_policy":3, "permanent_login":1}
]


def categories() -> List[models.CategoryDef]:
    """Generate data for current arXiv categories."""
    return [
        models.CategoryDef(
            category=category,
            name=data.full_name,
            active=1
        ) for category, data in CATEGORIES.items()
    ]


def policy_classes() -> List[models.TapirPolicyClass]:
    """Generate policy classes."""
    return [models.TapirPolicyClass(**datum) for datum in POLICY_CLASSES]


def users(count: int = 500) -> List[models.TapirUser]:
    """Generate a bunch of random users."""
    _users = []
    for i in range(count):
        locale = _get_locale()
        person = Person(locale)
        net = Internet()
        ip_addr = net.ip_v4()
        _users.append(models.TapirUser(
            first_name=person.name(),
            last_name=person.surname(),
            suffix_name=person.title(),
            share_first_name=1,
            share_last_name=1,
            email=person.email(),
            share_email=8,
            email_bouncing=0,
            policy_class=2,  # Public user.
            joined_date=_epoch(Datetime(locale).datetime()),
            joined_ip_num=ip_addr,
            joined_remote_host=ip_addr
        ))
    return _users


def licenses() -> List[models.License]:
    """Generate licenses."""
    return [models.License(**datum) for datum in LICENSES]


def _engine(uri, echo):
    engine = create_engine(uri, echo=echo)
    from arxiv.db import models
    models.configure_db_engine(engine, None)
    return engine

def create_all_legacy_db(test_db_file: str=DEV_SQLITE_FILE, echo: bool=False, uri:Optional[str]=None):
    """Legacy sqlite testing db with all tables created but no data."""
    url =  f"sqlite:///{test_db_file}" if uri is None else uri
    engine = _engine(url, echo)
    if engine.dialect.has_table(engine.connect(), "arXiv_submissions"):
        logger.info("Not making tables since arXiv_submissions already exists.")
    else:
        with Session(engine) as session:
            models.metadata.create_all(bind=engine)
            session.commit()

    return (engine, url, test_db_file)



def bootstrap_db(output_jwt: bool=False, db_uri = f"sqlite:///{DEV_SQLITE_FILE}"):
    """
    Creates db if it does not exist and loads some tables.

    It will:
    - add licenses
    - add categories
    - add policy classes
    - add fake tests users

    ARGS:
        output_jwt: bool Write to stdout a jwt of a user on completion of script
    """
    from arxiv.config import settings
    settings.CLASSIC_DB_URI = db_uri

    app = Flask("bootstrap")
    app.url_map.strict_slashes = False
    app.config["JWT_SECRET"] = os.getenv("JWT_SECRET", "FOOBAR")
    app.config.from_object(settings)
    Base(app)
    auth.Auth(app)
    from arxiv.db import init as db_init
    # bdc34: I'm having a lot of problems getting the db to work
    db_init(settings)  # only setups connection

    scope = [
        scopes.READ_PUBLIC,
        scopes.CREATE_SUBMISSION,
        scopes.EDIT_SUBMISSION,
        scopes.VIEW_SUBMISSION,
        scopes.DELETE_SUBMISSION,
        scopes.READ_UPLOAD,
        scopes.WRITE_UPLOAD,
        scopes.DELETE_UPLOAD_FILE,
        scopes.READ_UPLOAD_LOGS,
        scopes.READ_COMPILE,
        scopes.CREATE_COMPILE,
        scopes.READ_PREVIEW,
        scopes.CREATE_PREVIEW
    ]

    engine = _engine(db_uri, False)

    with app.app_context():
        logger.debug('loaded webapp')
        if app.config.get('JWT_SECRET', None):
            logger.debug(f'JWT_SECRET: {app.config["JWT_SECRET"]}')
        else:
            raise ValueError('Must set JWT_SECRET')

        def user_to_jwt(user):
            return generate_token(
                str(user.user_id),
                user.email,
                user.email,
                scope=scope,
                first_name=user.first_name,
                last_name=user.last_name,
                suffix_name=user.suffix_name,
                #endorsements=["*.*"],
            )

        with Session(engine) as session:
            logger.info("Waiting for database server to be available")
            logger.info(app.config["CLASSIC_DB_URI"])

            wait = 2
            while True:
                try:
                    session.execute(text("SELECT 1"))
                    break
                except Exception as e:
                    logger.info(e)
                    logger.info(f"...waiting {wait} seconds...")
                    time.sleep(wait)
                    wait *= 2

            logger.info("Checking for database")

            if not engine.dialect.has_table(engine.connect(), "arXiv_submissions"):
                created_users = []
                logger.info("Database for classic not yet initialized; creating all tables")
                models.metadata.create_all(engine)

                logger.info("Populate with base data")
                for obj in licenses():
                    session.add(obj)
                session.commit()
                logger.info("Added %i licenses", len(licenses()))
                for obj in policy_classes():
                    session.add(obj)
                session.commit()
                logger.info("Added %i policy classes", len(policy_classes()))
                for obj in categories():
                    session.add(obj)
                session.commit()
                logger.info("Added %i categories", len(categories()))
                users_to_add = users(10)
                for obj in users_to_add:
                    session.add(obj)
                    created_users.append(obj)
                logger.info("Added %i users for testing", len(users_to_add))
                session.commit()

                if output_jwt:
                    print(user_to_jwt(created_users[0]))
                else:
                    for user in created_users:
                        print(user.user_id, user.email)
                        print(user_to_jwt(user))

            else:
                logger.info("arXiv_submissions table already exists, DB bootstraped. No new users created.")
                if output_jwt:
                    print(user_to_jwt(session.query(models.User).first()))



if __name__ == "__main__":
    fire.Fire({
        "create_tables":create_all_legacy_db,
        "bootstrap_db": bootstrap_db,
    })
