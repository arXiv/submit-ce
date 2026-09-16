"""The three deposit gates.

Reproduces what ``arxiv-lib/t/arxiv_atompp/auth.t`` asserts about who may deposit,
as behaviour of `submit_ce.sword.auth` rather than as assertions about a shared
database. Order matters: credentials, then privilege, then license
(``AtomPP.pm:144-197``).
"""

from datetime import datetime, timezone

import arxiv.db.models as models
import pytest
from arxiv.db import Session

from submit_ce.sword import auth
from submit_ce.sword.errors import SwordFault

SITE = "arxiv.org"


def _fault(excinfo) -> SwordFault:
    return excinfo.value


# ------------------------------------------------------------- authenticate


def test_authenticate_returns_the_user_id(depositor):
    assert auth.authenticate(Session, depositor.nickname,
                             depositor.password) == depositor.user_id


def test_authenticate_rejects_an_unknown_nickname(sword_db):
    with pytest.raises(SwordFault) as excinfo:
        auth.authenticate(Session, "nobody", "whatever")
    assert _fault(excinfo).error.mnemonic == "EAUTH"
    assert _fault(excinfo).status == 401


def test_authenticate_rejects_a_wrong_password(depositor):
    with pytest.raises(SwordFault) as excinfo:
        auth.authenticate(Session, depositor.nickname, "wrong")
    assert _fault(excinfo).error.mnemonic == "EAUTH"


def test_authenticate_is_case_sensitive_in_the_nickname(depositor):
    """submit_sword.md:726-727."""
    with pytest.raises(SwordFault):
        auth.authenticate(Session, depositor.nickname.upper(), depositor.password)


def test_authenticate_rejects_a_user_with_no_password_row(depositor):
    Session.delete(Session.get(models.TapirUsersPassword, depositor.user_id))
    Session.commit()
    with pytest.raises(SwordFault) as excinfo:
        auth.authenticate(Session, depositor.nickname, depositor.password)
    assert _fault(excinfo).error.mnemonic == "EAUTH"


# ----------------------------------------------------------------- authorize


def test_authorize_accepts_a_privileged_user(depositor):
    auth.authorize(Session, depositor.user_id)  # must not raise


def test_authorize_rejects_a_user_without_the_flags(plain_user):
    """auth.t:53-63 -- neither flag_xml nor flag_proxy."""
    with pytest.raises(SwordFault) as excinfo:
        auth.authorize(Session, plain_user.user_id)
    assert _fault(excinfo).error.mnemonic == "EAUTH"
    assert _fault(excinfo).status == 401
    assert "special privileges" in _fault(excinfo).summary


@pytest.mark.parametrize("flag", ["flag_xml", "flag_proxy"])
def test_both_flags_are_required(depositor, flag):
    """``!($xmlflag && $proxyflag)`` -- either one missing is a refusal."""
    demographics = Session.get(models.Demographic, depositor.user_id)
    setattr(demographics, flag, 0)
    Session.commit()
    with pytest.raises(SwordFault):
        auth.authorize(Session, depositor.user_id)


@pytest.mark.parametrize("veto", ["no-endorse", "no-upload"])
def test_veto_status_must_be_ok(depositor, veto):
    demographics = Session.get(models.Demographic, depositor.user_id)
    demographics.veto_status = veto
    Session.commit()
    with pytest.raises(SwordFault):
        auth.authorize(Session, depositor.user_id)


def test_banned_user_is_refused(depositor):
    user = Session.get(models.TapirUser, depositor.user_id)
    user.flag_banned = 1
    Session.commit()
    with pytest.raises(SwordFault):
        auth.authorize(Session, depositor.user_id)


def test_missing_demographics_is_refused(sword_db):
    """Legacy's LEFT JOIN yields NULL flags, which are falsy."""
    with pytest.raises(SwordFault):
        auth.authorize(Session, 999999)


# ------------------------------------------------------------------ license


def test_registered_license_is_returned(depositor):
    assert auth.registered_license(Session, depositor.user_id, SITE) == \
        "http://arxiv.org/licenses/nonexclusive-distrib/1.0/"


def test_missing_license_is_a_precondition_failure(unlicensed_depositor):
    with pytest.raises(SwordFault) as excinfo:
        auth.registered_license(Session, unlicensed_depositor.user_id, SITE)
    assert _fault(excinfo).error.mnemonic == "ENLIC"
    assert _fault(excinfo).status == 412


def test_license_error_points_at_the_registration_page(unlicensed_depositor):
    with pytest.raises(SwordFault) as excinfo:
        auth.registered_license(Session, unlicensed_depositor.user_id, SITE)
    assert "https://arxiv.org/sword-license" in _fault(excinfo).summary


def test_a_stale_license_counts_as_absent(depositor):
    """AtomPP.pm:1553 requires the stored value to still be current."""
    row = Session.get(models.SwordLicense, depositor.user_id)
    row.license = "http://arxiv.org/licenses/retired/9.9/"
    Session.commit()
    with pytest.raises(SwordFault) as excinfo:
        auth.registered_license(Session, depositor.user_id, SITE)
    assert _fault(excinfo).error.mnemonic == "ENLIC"


# --------------------------------------------------------------- suspect email


def test_suspect_email_is_detected(suspect_author):
    """AtomPP.pm:1589-1607, asserted by 04-suspect.t."""
    assert auth.is_suspect_email(Session, suspect_author.email)


def test_ordinary_email_is_not_suspect(depositor):
    assert not auth.is_suspect_email(Session, depositor.email)


def test_unknown_email_is_not_suspect(sword_db):
    assert not auth.is_suspect_email(Session, "stranger@example.org")


# ------------------------------------------------------- the whole gate, in order


def test_depositor_from_credentials_builds_a_depositor(depositor):
    result = auth.depositor_from_credentials(
        Session, depositor.nickname, depositor.password, SITE)
    assert result.user_id == depositor.user_id
    assert result.nickname == depositor.nickname
    assert result.email == depositor.email
    assert result.license.endswith("nonexclusive-distrib/1.0/")
    assert set(result.collections) == {"physics", "cs", "test"}


def test_privilege_is_checked_before_license(plain_user):
    """An account with no privileges must not learn about its license state."""
    Session.add(models.SwordLicense(
        user_id=plain_user.user_id,
        license="http://arxiv.org/licenses/nonexclusive-distrib/1.0/",
        updated=datetime.now(timezone.utc)))
    Session.commit()

    with pytest.raises(SwordFault) as excinfo:
        auth.depositor_from_credentials(
            Session, plain_user.nickname, plain_user.password, SITE)
    assert _fault(excinfo).error.mnemonic == "EAUTH"


def test_credentials_are_checked_before_privilege(plain_user):
    """A wrong password on an unprivileged account still reports EAUTH."""
    with pytest.raises(SwordFault) as excinfo:
        auth.depositor_from_credentials(
            Session, plain_user.nickname, "wrong", SITE)
    assert _fault(excinfo).error.mnemonic == "EAUTH"


# -------------------------------------------------------------- X-On-Behalf-Of


def test_resolve_on_behalf_of_finds_a_nickname(depositor):
    assert auth.resolve_on_behalf_of(Session, depositor.nickname) == \
        depositor.user_id


def test_resolve_on_behalf_of_ignores_empty_and_unknown(sword_db):
    assert auth.resolve_on_behalf_of(Session, None) is None
    assert auth.resolve_on_behalf_of(Session, "") is None
    assert auth.resolve_on_behalf_of(Session, "nobody") is None
