"""Depositor fixtures for the SWORD suite.

Replaces ``arxiv-lib/t/lib/Test/DB.pm`` plus the ``arXiv_sword_licenses.sql``
seed. ``arxiv-lib/t/arxiv_atompp/auth.t:20-63`` asserts the exact conditions a
SWORD depositor must satisfy, against three fixed accounts in a shared database:

* ``vtex`` (55596) and ``mscmt`` (91310) -- ``flag_xml`` and ``flag_proxy`` set,
  ``veto_status == 'ok'``, not banned, and a row in ``arXiv_sword_licenses``.
* ``test_arx_user_accoun`` (109519) -- neither flag, and no license row.

Those are reproduced here as `depositor`, `unlicensed_depositor` and
`plain_user`, built into a throwaway sqlite database instead of depending on
whatever the shared dev database happens to contain. A fourth, `suspect_author`,
covers ``04-suspect.t``: an account carrying ``flag_suspect``, whose email must be
refused as a contact address.
"""

import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import arxiv.db.models as models
import pytest
from arxiv.auth.legacy.passwords import hash_password
from arxiv.db import Session, session_factory

from submit_ce.make_test_db import create_all_db
from submit_ce.ui.config import settings

NONEXCLUSIVE_LICENSE = "http://arxiv.org/licenses/nonexclusive-distrib/1.0/"
"""The license ``auth.t:27`` expects on a SWORD-enabled account."""


@dataclass(frozen=True)
class Depositor:
    """A SWORD account, as the tests need to talk about it."""

    user_id: int
    nickname: str
    password: str
    email: str


def _make_user(*,
               user_id: int,
               nickname: str,
               password: str,
               email: str,
               flag_xml: int = 0,
               flag_proxy: int = 0,
               flag_suspect: int = 0,
               flag_banned: int = 0,
               veto_status: str = "ok",
               groups: tuple = ("physics", "cs", "test"),
               license: Optional[str] = None) -> Depositor:
    """Insert a user plus nickname, demographics, password and license row."""
    group_flags = {f"flag_group_{name}": int(name in groups)
                   for name in ("physics", "math", "cs", "nlin", "test",
                                "q_bio", "q_fin", "stat", "eess", "econ")}

    user = models.TapirUser(
        user_id=user_id,
        email=email,
        first_name="Test",
        last_name=nickname,
        policy_class=2,
        flag_email_verified=1,
        flag_approved=1,
        flag_banned=flag_banned,
        demographics=models.Demographic(
            country="us",
            affiliation="Cornell University",
            type=3,
            url=f"https://example.org/{nickname}",
            archive="",
            subject_class="",
            original_subject_classes="",
            flag_proxy=flag_proxy,
            flag_xml=flag_xml,
            flag_suspect=flag_suspect,
            veto_status=veto_status,
            **group_flags,
        ),
        tapir_nicknames=models.TapirNickname(
            nickname=nickname, flag_valid=1, flag_primary=1),
    )
    Session.add(user)
    Session.add(models.TapirUsersPassword(
        user_id=user_id,
        password_storage=0,
        password_enc=hash_password(password)))
    if license is not None:
        # ``updated`` is NOT NULL with a server_default of CURRENT_TIMESTAMP in
        # the real MySQL schema. SQLAlchemy models it as FetchedValue(), which is
        # a marker rather than DDL, so sqlite's create_all emits no default and
        # the insert has to supply one.
        Session.add(models.SwordLicense(
            user_id=user_id,
            license=license,
            updated=datetime.now(timezone.utc)))
    Session.commit()

    return Depositor(user_id=user_id, nickname=nickname,
                     password=password, email=email)


@pytest.fixture(scope="function")
def sword_db():
    """An empty legacy schema on sqlite, bound to `arxiv.db.Session`.

    Function-scoped: these tests create and modify submissions, and sharing one
    database across them would make ordering matter.

    ``settings.CLASSIC_DB_URI`` is repointed as well, because `create_sword_app`
    wires its own engine from settings (`config_backend_api` calls
    ``configure_db`` and re-binds ``session_factory``). Without that the app would
    silently talk to the repo's checked-in ``legacy.db`` instead of this one. A
    file-backed database rather than ``:memory:`` so both engines see the schema.
    """
    tmp = tempfile.mkdtemp()
    path = Path(tmp) / "legacy.db"
    engine, url, _path = create_all_db(str(path))

    previous_uri = settings.CLASSIC_DB_URI
    settings.CLASSIC_DB_URI = url
    session_factory.configure(bind=engine)
    Session.remove()
    try:
        yield engine
    finally:
        Session.remove()
        settings.CLASSIC_DB_URI = previous_uri
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def sword_app(sword_db):
    """The SWORD FastAPI app, wired to the fixture database."""
    from submit_ce.sword.app import create_sword_app
    return create_sword_app()


@pytest.fixture
def client(sword_app):
    """A `TestClient` over the app; ASGI in-process, so no sockets are opened."""
    from fastapi.testclient import TestClient
    return TestClient(sword_app)


@pytest.fixture
def depositor(sword_db) -> Depositor:
    """A fully privileged, licensed depositor -- ``vtex``/``mscmt`` in auth.t."""
    return _make_user(
        user_id=55596,
        nickname="vtex",
        password="sword-test-password",
        email="vtex@example.org",
        flag_xml=1,
        flag_proxy=1,
        license=NONEXCLUSIVE_LICENSE,
    )


@pytest.fixture
def unlicensed_depositor(sword_db) -> Depositor:
    """Privileged but with no ``arXiv_sword_licenses`` row -> 412 ENLIC."""
    return _make_user(
        user_id=91310,
        nickname="mscmt",
        password="sword-test-password",
        email="mscmt@example.org",
        flag_xml=1,
        flag_proxy=1,
        license=None,
    )


@pytest.fixture
def plain_user(sword_db) -> Depositor:
    """Neither flag and no license -- ``test_arx_user_accoun`` in auth.t."""
    return _make_user(
        user_id=109519,
        nickname="test_arx_user_accoun",
        password="sword-test-password",
        email="plain@example.org",
        flag_xml=0,
        flag_proxy=0,
        license=None,
    )


@pytest.fixture
def suspect_author(sword_db) -> Depositor:
    """An account flagged ``flag_suspect`` (``AtomPP.pm:1589-1607``).

    Naming this address as the contact author must be refused with EVCML, whether
    it arrives via ``X-On-Behalf-Of`` or as a contributor email -- see
    ``04-suspect.t``.
    """
    return _make_user(
        user_id=120001,
        nickname="suspect",
        password="sword-test-password",
        email="suspect@example.org",
        flag_suspect=1,
    )
