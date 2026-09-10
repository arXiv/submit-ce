"""The depositor fixtures must satisfy exactly what auth.t asserts.

``arxiv-lib/t/arxiv_atompp/auth.t:20-63`` is the specification of who may deposit:
``flag_xml`` **and** ``flag_proxy`` set, ``veto_status == 'ok'``, not
``flag_banned``, plus a row in ``arXiv_sword_licenses`` whose value is a current
license (``AtomPP.pm:183-197``, ``AtomPP.pm:1544-1558``).

These tests pin the fixtures rather than the implementation -- the authorization
code itself arrives in the next step. Getting them wrong would make that step's
tests pass or fail for the wrong reason.
"""

import arxiv.db.models as models
import pytest
from arxiv.auth.legacy.exceptions import PasswordAuthenticationFailed
from arxiv.auth.legacy.passwords import check_password
from arxiv.db import Session

from submit_ce.sword.tests.conftest import NONEXCLUSIVE_LICENSE


def _demographics(user_id: int) -> models.Demographic:
    return Session.get(models.Demographic, user_id)


def _user(user_id: int) -> models.TapirUser:
    return Session.get(models.TapirUser, user_id)


def _license(user_id: int):
    return Session.get(models.SwordLicense, user_id)


# ------------------------------------------------------- the licensed depositor


def test_depositor_satisfies_every_gate_condition(depositor):
    """auth.t:20-37, for vtex/55596."""
    user = _user(depositor.user_id)
    extras = _demographics(depositor.user_id)

    assert user is not None
    assert not user.flag_banned
    assert extras.flag_xml
    assert extras.flag_proxy
    assert extras.veto_status == "ok"


def test_depositor_has_the_standard_arxiv_license(depositor):
    """auth.t:26-27."""
    row = _license(depositor.user_id)
    assert row is not None
    assert row.license == NONEXCLUSIVE_LICENSE


def test_depositor_nickname_is_resolvable(depositor):
    """The gate looks a user up by nickname (AtomPP.pm:172)."""
    nickname = Session.query(models.TapirNickname).filter_by(
        nickname=depositor.nickname).one()
    assert nickname.user_id == depositor.user_id


def test_depositor_password_verifies(depositor):
    """Basic auth has to be able to authenticate these accounts."""
    row = Session.get(models.TapirUsersPassword, depositor.user_id)
    assert row is not None
    assert check_password(depositor.password, row.password_enc) is True


def test_depositor_password_rejects_the_wrong_password(depositor):
    """check_password raises rather than returning False, so assert on that.

    Also confirms the stored value is a real salted hash and not something that
    matches anything.
    """
    row = Session.get(models.TapirUsersPassword, depositor.user_id)
    with pytest.raises(PasswordAuthenticationFailed):
        check_password("not-the-password", row.password_enc)


def test_depositor_is_not_suspect(depositor):
    assert not _demographics(depositor.user_id).flag_suspect


# ----------------------------------------------------- the unlicensed depositor


def test_unlicensed_depositor_is_privileged_but_has_no_license(unlicensed_depositor):
    """Isolates the 412 ENLIC precondition from the 401 EAUTH gate."""
    extras = _demographics(unlicensed_depositor.user_id)
    assert extras.flag_xml
    assert extras.flag_proxy
    assert extras.veto_status == "ok"
    assert _license(unlicensed_depositor.user_id) is None


# -------------------------------------------------------------- the plain user


def test_plain_user_has_neither_flag_and_no_license(plain_user):
    """auth.t:53-63, for test_arx_user_accoun/109519."""
    user = _user(plain_user.user_id)
    extras = _demographics(plain_user.user_id)

    assert not user.flag_banned
    assert not extras.flag_xml
    assert not extras.flag_proxy
    assert extras.veto_status == "ok"
    assert _license(plain_user.user_id) is None


# ------------------------------------------------------------ the suspect author


def test_suspect_author_is_flagged(suspect_author):
    """AtomPP.pm:1589-1607 refuses this address as a contact author."""
    assert _demographics(suspect_author.user_id).flag_suspect


def test_suspect_author_is_findable_by_email(suspect_author):
    """_is_email_bad joins tapir_users on email, not on user_id."""
    user = Session.query(models.TapirUser).filter_by(
        email=suspect_author.email).one()
    assert user.user_id == suspect_author.user_id


# ------------------------------------------------------------------- isolation


@pytest.mark.parametrize("run", [1, 2])
def test_fixtures_are_isolated_between_tests(depositor, run):
    """The database is function-scoped, so a re-created user must not collide."""
    assert _user(depositor.user_id) is not None
    assert Session.query(models.TapirUser).count() == 1
