"""Bootstraps users and other DB entities for testing/dev."""

from arxiv.auth.legacy import accounts
from arxiv.auth.legacy.sessions import create
from arxiv.base import Base
from arxiv.taxonomy.category import Category
from arxiv.taxonomy.definitions import CATEGORIES, CATEGORIES_ACTIVE, GROUPS
from flask import Flask
from sqlalchemy.orm import Session

if __name__ == '__main__':
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).resolve().parent.parent))

import logging
import random
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import fire
from arxiv.auth import domain
from arxiv.auth.auth import Auth, tokens
from arxiv.db import models
from mimesis import Internet, Person
from mimesis.locales import Locale
from sqlalchemy import create_engine, text

from submit_ce.ui.config import DEV_SQLITE_FILE, settings

logging.basicConfig()
logging.getLogger("arxiv.submission.services.classic.interpolate").setLevel(logging.ERROR)
logging.getLogger("arxiv.base.alerts").setLevel(logging.ERROR)
logging.getLogger("arxiv.vault.middleware").setLevel(logging.CRITICAL)

logger = logging.getLogger(__file__)

LOCALES = list(Locale)

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


def get_endorsements() -> Tuple[List[Category], Category, str]:
    """Randomly return `[endorsements, default_category, group]`."""
    group = random.choice([item for item in GROUPS.values() if item.is_active]).id
    categories=random.sample(list(CATEGORIES_ACTIVE.values()), k=random.randint(4,16))
    return categories, random.choice(categories), group


def users_v2(count: int = 500) -> List[Tuple[domain.User, str, str, str, List[Category]]]:
    """Generate a bunch of random users for use with `accounts.register()`."""
    _users=[]
    for ii in range(count):
        locale = random.choice(LOCALES)
        person = Person(locale)
        net = Internet()
        endorsed, default_category, group = get_endorsements()
        _users.append(
            (
            domain.User(
                user_id=str(ii),
                email=person.email(),
                username=person.username(),
                name=domain.UserFullName(
                    forename=person.name(),
                    surname=person.surname(),
                    suffix=person.title()),
                profile=domain.UserProfile(
                    affiliation=person.university(),
                    rank=3,
                    country=str(locale)[:2],
                    default_archive=default_category,
                    submission_groups=[group]
            )),
            person.password(),
            net.ip_v4(),
            net.hostname(),
            endorsed
            )
        )
    return _users


def licenses() -> List[models.License]:
    """Generate licenses."""
    return [models.License(**datum) for datum in LICENSES]


def wait_for_db(session, app):
    logger.info(f"Waiting for database server to be available {app.config['CLASSIC_DB_URI']}")
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


def _engine(uri, echo):
    engine = create_engine(uri, echo=echo)
    from arxiv.db import models
    models.configure_db_engine(engine, None)
    return engine

def create_all_legacy_db(test_db_file: str=DEV_SQLITE_FILE, echo: bool=False, uri:Optional[str]=None):
    """Legacy sqlite testing db with all tables created but no data."""
    url =  f"sqlite:///{test_db_file}" if uri is None else uri
    engine = _engine(url, echo)
    logger.setLevel(logging.DEBUG)

    if engine.dialect.has_table(engine.connect(), "arXiv_submissions"):
        logger.info("Not making tables since arXiv_submissions already exists.")
    else:
        with Session(engine) as session:
            models.metadata.create_all(bind=engine)
            session.commit()

    return engine, url, test_db_file


def bootstrap_db(output_jwt: bool=False, db_uri = f"sqlite:///{DEV_SQLITE_FILE}", jwt_secret: str = settings.JWT_SECRET):
    """Creates db if it does not exist, load standard data to tables, create
    fake users.

    This script will wait for the DB to become available and then check if the
    arXiv_submissions table exists.

    If the table exists it will not make tables or load data. If `output_jwt` is
    `True` it will make a auth session in the db for the first user and write to
    stdout a JWT. NOTE that this will alter an existing DB by only maknig a auth
    session.

    If the table doesn't exist, this script will create all the legacy tables,
    add standard data like licenses, create several testing users. If
    `output_jwt` is `True` it will make a auth session in the db for the first
    user and write to stdout a JWT.

    If it makes a auth session the session will be 1 year long so it can be
    reused by devs.

    Ex:

        python tests/make_tests_db.py --output-single-jwt > jwt.txt
        INTEGRATION_JWT = $(cat jwt.txt) python -m submit.integration.test_integration

    Testing and debugging this script outside of docker can be done like:

       JWT_SECRET='X' CLASSIC_DATABASE_URI='sqlite:///tmpbootstrap.db.sqlite' python tests/make_tests_db.py

    ARGS:
        output_jwt: bool Write to stdout a jwt of a user on completion of script
    """
    logger.setLevel(logging.DEBUG)

    from arxiv.config import settings
    settings.CLASSIC_DB_URI = db_uri

    app = Flask("bootstrap")
    app.url_map.strict_slashes = False
    app.config["JWT_SECRET"] = jwt_secret
    logger.debug(f'JWT_SECRET: {app.config["JWT_SECRET"]}')
    app.config.from_object(settings)
    Base(app)
    Auth(app)

    from arxiv.db import init as db_init
    db_init(settings)  # only setups connection, does not make tables
    engine = _engine(db_uri, False)

    with app.app_context():
        app.config['SESSION_DURATION']=30758400  # a year, make this as long as you want.
        def user_to_jwt(user, auths):
            session = create(auths, "127.0.0.1", "localhost", "", user)
            return tokens.encode(session, app.config["JWT_SECRET"])

        with Session(engine) as session:
            wait_for_db(session, app)
            if engine.dialect.has_table(engine.connect(), "arXiv_submissions"):
                logger.info("arXiv_submissions table already exists, DB bootstraped. No new users created.")
                if output_jwt:
                    jwt = user_to_jwt(session.query(models.TapirUser).first())
                    print("\n")
                return ""

            logger.info("Database for classic not yet initialized; creating all tables")
            models.metadata.create_all(engine)

            logger.info("Populate with base data")
            for obj in licenses():
                session.add(obj)
            session.commit()
            logger.debug("Added %i licenses", len(licenses()))
            for obj in policy_classes():
                session.add(obj)
            session.commit()
            logger.debug("Added %i policy classes", len(policy_classes()))
            for obj in categories():
                session.add(obj)
            session.commit()
            logger.debug("Added %i categories", len(categories()))

            users_to_add = users_v2(10)
            created_users = []
            for user, pw, ip, host, endos in users_to_add:
                new_user, auths = accounts.register(user, pw, ip, host)
                for cat in endos:
                    if cat.in_archive == cat.id:  # it's an archive, ex nucl-th
                        session.add(models.Endorsement(endorsee_id=new_user.user_id,
                                                   archive=cat.in_archive,
                                                   subject_class="",
                                                   flag_valid=1, type="auto", point_value=10,
                                                   issued_when=11074371513))
                    else:
                        sc = cat.id.split(".")[1] if "." in cat.id else cat.id
                        session.add(models.Endorsement(endorsee_id=new_user.user_id,
                                                   archive=cat.in_archive,
                                                   subject_class=sc,
                                                   flag_valid=1, type="auto", point_value=10,
                                                   issued_when=11074371513))
                created_users.append((new_user, auths))
            logger.info("Added %i users for testing", len(users_to_add))
            session.commit()

            jwt = user_to_jwt(created_users[0][0], created_users[0][1])
            if output_jwt:
                print(jwt)
            return ""


if __name__ == "__main__":
    fire.Fire({
        "create_tables":create_all_legacy_db,
        "bootstrap_db": bootstrap_db,
    })
