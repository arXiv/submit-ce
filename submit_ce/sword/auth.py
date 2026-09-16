"""Authentication and authorization for SWORD deposits.

Three gates, in the order ``AtomPP.pm:144-197`` applies them:

1. **HTTP Basic credentials.** New code. Legacy never checked these itself --
   Apache did, via ``mod_authnz_external`` piped to ``cgi-bin/authenticate.pl``
   (``arxiv-httpd/conf/sword.conf:10-13``), so the CGI simply trusted
   ``REMOTE_USER``. Running in-process means doing it here.
2. **Deposit privilege.** ``flag_xml`` *and* ``flag_proxy`` set, ``veto_status ==
   'ok'``, not ``flag_banned`` -> otherwise 401 EAUTH (``AtomPP.pm:183-189``).
3. **A registered default license.** A row in ``arXiv_sword_licenses`` whose value
   is a current license -> otherwise 412 ENLIC (``AtomPP.pm:191-197``,
   ``AtomPP.pm:1544-1558``).

The username is a tapir **nickname**, compared case-sensitively
(``submit_sword.md:726-727``).

One deliberate difference: a bad password gets a ``sword:error`` body with the
``WWW-Authenticate`` challenge, where legacy returned Apache's stock HTML error
page. Every other SWORD failure is already a ``sword:error``, and the challenge
header is what makes a client re-prompt.
"""

from dataclasses import dataclass
from typing import List, Optional

import arxiv.db.models as models
from arxiv.auth.legacy.exceptions import PasswordAuthenticationFailed
from arxiv.auth.legacy.passwords import check_password
from arxiv.license import CURRENT_LICENSES
from sqlalchemy.orm import Session as SqlalchemySession

from submit_ce.sword import collections
from submit_ce.sword.errors import SwordFault

REALM = "SWORD at arXiv"
"""``AuthName`` in sword.conf:29 and ``AtomPP.pm:155``."""

WWW_AUTHENTICATE = f'Basic realm="{REALM}"'

NOT_PRIVILEGED_DETAIL = (
    "SWORD deposit requires special privileges. "
    "Contact the server administrator."
)
"""Verbatim from ``AtomPP.pm:187``."""


def _no_license_detail(site: str) -> str:
    """``AtomPP.pm:195``, which names the page where a license is registered."""
    return ('The submitter must have a valid "license" registered with their '
            f"profile at arXiv. Please visit https://{site}/sword-license to "
            "set a default license")


@dataclass(frozen=True)
class Depositor:
    """An authenticated, authorized SWORD depositor."""

    user_id: int
    nickname: str
    email: str
    license: str
    groups: List[str]

    @property
    def collections(self) -> List[str]:
        """Collection names this depositor may post to."""
        return [collections.collection_name(gid) for gid in self.groups]


def authenticate(session: SqlalchemySession, username: str,
                 password: str) -> int:
    """Verify Basic credentials and return the user id.

    Raises `SwordFault` EAUTH (401) for an unknown nickname, a missing password
    row, or a wrong password -- the three are deliberately indistinguishable to
    the caller.
    """
    user_id = collections.nickname_to_user_id(session, username)
    if user_id is None:
        raise SwordFault("EAUTH", "no such user")

    stored = session.get(models.TapirUsersPassword, user_id)
    if stored is None or not stored.password_enc:
        raise SwordFault("EAUTH", "no password on file")

    try:
        check_password(password, stored.password_enc)
    except PasswordAuthenticationFailed:
        raise SwordFault("EAUTH", "bad password") from None

    return user_id


def authorize(session: SqlalchemySession, user_id: int) -> None:
    """Apply the deposit-privilege gate (``AtomPP.pm:183``).

    Legacy joins demographics to tapir_users and requires
    ``flag_xml AND flag_proxy``, ``veto_status == 'ok'`` and not ``flag_banned``.
    A missing demographics row fails, matching the Perl -- its LEFT JOIN yields
    NULL flags, which are falsy.
    """
    user = session.get(models.TapirUser, user_id)
    demographics = session.get(models.Demographic, user_id)

    if user is None or demographics is None:
        raise SwordFault("EAUTH", NOT_PRIVILEGED_DETAIL)
    if not (demographics.flag_xml and demographics.flag_proxy):
        raise SwordFault("EAUTH", NOT_PRIVILEGED_DETAIL)
    if demographics.veto_status != "ok":
        raise SwordFault("EAUTH", NOT_PRIVILEGED_DETAIL)
    if user.flag_banned:
        raise SwordFault("EAUTH", NOT_PRIVILEGED_DETAIL)


def registered_license(session: SqlalchemySession, user_id: int,
                       site: str) -> str:
    """Return the depositor's default license, or raise ENLIC (412).

    The stored value must still be a *current* license; a stale one counts as
    absent (``AtomPP.pm:1553``).
    """
    row = session.get(models.SwordLicense, user_id)
    if row is None or not row.license or row.license not in CURRENT_LICENSES:
        raise SwordFault("ENLIC", _no_license_detail(site))
    return row.license


def is_suspect_email(session: SqlalchemySession, email: str) -> bool:
    """Whether ``email`` belongs to an account flagged ``flag_suspect``.

    ``AtomPP.pm:1589-1607`` refuses such an address as the contact author, with
    EVCML and "must submit directly". Note it joins on ``tapir_users.email``, so
    any account with that address counts, and it checks only ``flag_suspect`` --
    ``flag_banned`` is selected but never consulted.
    """
    user = session.query(models.TapirUser).filter_by(email=email).first()
    if user is None:
        return False
    demographics = session.get(models.Demographic, user.user_id)
    return bool(demographics and demographics.flag_suspect)


def depositor_from_credentials(session: SqlalchemySession,
                               username: str,
                               password: str,
                               site: str) -> Depositor:
    """Run all three gates and build a `Depositor`.

    Order matters: authentication before privilege before license, so a client
    without an account never learns whether it would have had a license.
    """
    user_id = authenticate(session, username, password)
    authorize(session, user_id)
    license_uri = registered_license(session, user_id, site)

    user = session.get(models.TapirUser, user_id)
    return Depositor(
        user_id=user_id,
        nickname=username,
        email=user.email if user else "",
        license=license_uri,
        groups=collections.groups_for_user(session, user_id),
    )


def resolve_on_behalf_of(session: SqlalchemySession,
                         value: Optional[str]) -> Optional[int]:
    """User id for an ``X-On-Behalf-Of`` nickname, if it names one.

    The header is overloaded in legacy: for a service-document request it is a
    *nickname* whose privileges shape the response (``AtomPP.pm:356-361``), while
    on a deposit it is a contact author as ``"Name" <email>``
    (``AtomPP.pm:866-891``). Only the nickname reading belongs here.
    """
    if not value:
        return None
    return collections.nickname_to_user_id(session, value)
