"""Register a default license for SWORD deposits.

Ports ``arxiv-httpd/cgi-bin/sword_license.pl``. SWORD has no place in the protocol
to negotiate a license, so arXiv requires depositors to pick one in advance; a
deposit without one on file is refused with 412 ENLIC
(``submit_sword.md:122-127``).

This lives in the Flask UI rather than the SWORD API because it is an HTML page
under ordinary cookie auth -- ``arxiv-httpd/conf/sword.conf`` puts ``/sword-app``
and ``/ppw`` behind basic auth but leaves ``/sword-license`` alone.

Two behaviours from the Perl worth keeping in mind:

* "no license" is stored as the **literal string** ``'no'``, not NULL
  (``sword_license.pl:96``). Reading back returns ``$license || 'no'``, so an absent
  row and an explicit refusal look the same to the page. The deposit gate rejects
  both, since ``'no'`` is not a current license (``AtomPP.pm:1553``).
* Any submitted value is stored without validation -- the Perl has a bare
  ``# FIXME - check valid`` there. Here the value must be one the page offers.
"""

import logging
from datetime import datetime, timezone
from typing import Tuple

import arxiv.db.models as models
from arxiv.auth.domain import Session
from arxiv.db import Session as DB
from arxiv.license import CURRENT_LICENSES
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import BadRequest

logger = logging.getLogger(__name__)

NO_LICENSE = "no"
"""The value stored when a depositor declines to choose (``sword_license.pl:96``)."""

NO_LICENSE_LABEL = "No license selected -- SWORD deposits will be refused"


def offered_licenses() -> list:
    """The licenses the page offers, in display order, with ``no`` last.

    Mirrors ``current_licenses(), 'no'`` at ``sword_license.pl:53``.
    """
    ordered = sorted(CURRENT_LICENSES.items(),
                     key=lambda item: item[1].get("order", 0))
    licenses = [{"uri": uri, "label": info.get("label") or uri}
                for uri, info in ordered]
    licenses.append({"uri": NO_LICENSE, "label": NO_LICENSE_LABEL})
    return licenses


def get_license(user_id: int) -> str:
    """The depositor's stored license, or ``'no'`` when there is none."""
    row = DB.get(models.SwordLicense, user_id)
    if row is None or not row.license:
        return NO_LICENSE
    return row.license


def set_license(user_id: int, license_uri: str) -> None:
    """Store the depositor's choice, replacing any previous one.

    ``timestamp``-style columns on this table are NOT NULL with a
    ``FetchedValue()`` default, which MySQL fills from ``CURRENT_TIMESTAMP`` but
    sqlite has no DDL default for, so ``updated`` is set explicitly.
    """
    row = DB.get(models.SwordLicense, user_id)
    now = datetime.now(timezone.utc)
    if row is None:
        DB.add(models.SwordLicense(user_id=user_id, license=license_uri,
                                   updated=now))
    else:
        row.license = license_uri
        row.updated = now
    DB.commit()


def sword_license(method: str, params: MultiDict, session: Session,
                  *args, **kwargs) -> Tuple[dict, int, dict]:
    """Show, and on POST update, the depositor's default SWORD license."""
    if session is None or not session.user:
        raise BadRequest("No authenticated user")
    user_id = int(session.user.user_id)

    if method == "POST":
        chosen = params.get("License")
        valid = {entry["uri"] for entry in offered_licenses()}
        if not chosen:
            raise BadRequest("No License value supplied")
        if chosen not in valid:
            # The Perl stored whatever arrived, with a `# FIXME - check valid`.
            raise BadRequest(f"Not an offered license: {chosen}")
        set_license(user_id, chosen)
        logger.info("user %s set SWORD license to %s", user_id, chosen)

    return ({"licenses": offered_licenses(),
             "selected": get_license(user_id)},
            200, {})
