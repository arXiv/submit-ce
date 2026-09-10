"""Parse and verify SWORD request headers.

Ports ``process_sword_headers`` (``AtomPP.pm:849-915``) plus the MD5 checks at
``AtomPP.pm:1501-1510``.

``X-On-Behalf-Of`` is overloaded in the protocol: on a service-document request it
is a bare *nickname* whose privileges shape the response (``AtomPP.pm:356-361``),
while on a deposit it is the **contact author** as ``"Name" <email>``
(``AtomPP.pm:866-891``). Only the deposit reading lives here; the nickname reading
is `submit_ce.sword.auth.resolve_on_behalf_of`.
"""

import base64
import hashlib
import re
from dataclasses import dataclass
from email.utils import parseaddr
from typing import Mapping, Optional, Tuple

from email_validator import EmailNotValidError, validate_email

from submit_ce.sword.errors import SwordFault

ACCEPTED_PACKAGING = frozenset({
    "http://purl.org/net/sword-types/bagit",
    "http://arxiv.org/schemas/zipit",
})
"""Packaging values a deposit may declare.

``Config.pm:200-206`` maps four values, but ``mets/dspace`` is mapped to ``0`` --
falsy, so ``AtomPP.pm:907`` rejects it. ``datapub.dataconservancy.org/package`` was
truthy there, but its handler is dead code (plan decision 2), so it is rejected
here too rather than accepted and then failing deeper in.
"""

ON_BEHALF_OF_FORMAT_HELP = (
    "The X-On-Behalf-Of header must have a username and valid email in the "
    'format: "J. Doe" <jdoe@somewhere.com>'
)
"""Verbatim from ``AtomPP.pm:881``."""

_FILENAME = re.compile(r"filename\s*=\s*([^;\s]+)")
_ASCII = re.compile(r"([ -~]+)")


@dataclass(frozen=True)
class DepositHeaders:
    """The SWORD extension headers on a deposit request."""

    content_type: str
    md5: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    on_behalf_of: Optional[str] = None
    verbose: bool = False
    no_op: bool = False
    packaging: Optional[str] = None
    user_agent: Optional[str] = None
    filename: Optional[str] = None


def parse_on_behalf_of(value: str) -> Tuple[str, str]:
    """Split ``"A. Scientist" <a@b.edu>`` into a name and an address.

    Legacy runs ``Email::Valid->address`` and refuses the header outright when it
    finds no address (``AtomPP.pm:869-883``), which is EVCML. A bare address with
    no display name is accepted, with an empty name.

    Deliverability is deliberately **not** checked: that would make a DNS query per
    deposit, and the address only has to be well-formed for arXiv to mail it.

    RFC 2606 special-use domains (``.invalid``, ``.localhost``, ``.test``) *are*
    refused, which is stricter than legacy's syntax-only ``Email::Valid``. The
    contact address exists so arXiv can send the identifier and paper password
    (``submit_sword.md:68-72``); accepting an address that provably cannot receive
    mail guarantees that never arrives.
    """
    name, address = parseaddr(value or "")
    if not address:
        raise SwordFault("EVCML", ON_BEHALF_OF_FORMAT_HELP)
    try:
        validated = validate_email(address, check_deliverability=False)
    except EmailNotValidError:
        raise SwordFault("EVCML", ON_BEHALF_OF_FORMAT_HELP) from None
    return name.strip(), validated.normalized


def parse_disposition_filename(value: Optional[str]) -> Optional[str]:
    """Pull a filename out of ``Content-Disposition``.

    Legacy parses it and then ignores it (``AtomPP.pm:857-865``), keeping only the
    ASCII run of the value. Kept for the response's ``Content-Disposition`` echo.
    """
    if not value:
        return None
    match = _FILENAME.search(value)
    if not match:
        return None
    ascii_run = _ASCII.search(match.group(1))
    return ascii_run.group(1) if ascii_run else None


def is_no_op(value: Optional[str]) -> bool:
    """Whether ``X-No-Op`` is on.

    **Any** value except the literal ``"false"`` enables it, case-insensitively
    (``AtomPP.pm:896-901``) -- so an empty-but-present header switches it on. That
    is faithfully reproduced; it is why `submit_ce.sword.tests.client` omits the
    header rather than sending it blank.
    """
    if value is None:
        return False
    return value.strip().lower() != "false"


def parse_deposit_headers(headers: Mapping[str, str]) -> DepositHeaders:
    """Build a `DepositHeaders` from a request's headers.

    Raises `SwordFault` EVCML for an unusable ``X-On-Behalf-Of`` and EMDTP (415)
    for unsupported ``X-Packaging``.
    """
    def get(name: str) -> Optional[str]:
        return headers.get(name)

    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    on_behalf_of = get("X-On-Behalf-Of")
    # An empty header is treated as absent; legacy's `if (my $x = ...)` skips
    # falsy values too.
    if on_behalf_of:
        contact_name, contact_email = parse_on_behalf_of(on_behalf_of)
    else:
        on_behalf_of = None

    packaging = get("X-Packaging")
    if packaging:
        if packaging not in ACCEPTED_PACKAGING:
            raise SwordFault("EMDTP", f"unsupported packaging: {packaging}")
    else:
        packaging = None

    return DepositHeaders(
        content_type=(get("Content-Type") or "").strip(),
        md5=get("Content-MD5"),
        contact_name=contact_name,
        contact_email=contact_email,
        on_behalf_of=on_behalf_of,
        verbose=bool(get("X-Verbose")),
        no_op=is_no_op(get("X-No-Op")),
        packaging=packaging,
        user_agent=get("User-Agent"),
        filename=parse_disposition_filename(get("Content-Disposition")),
    )


def verify_md5(payload: bytes, supplied: Optional[str]) -> None:
    """Check ``Content-MD5`` if the client sent one.

    Both encodings legacy accepts: padded base64 of the digest, or the lowercase
    hex digest (``AtomPP.pm:1501-1510``). A mismatch is 412 EVMD5.
    """
    if not supplied:
        return
    digest = hashlib.md5(payload).digest()
    if supplied == base64.b64encode(digest).decode("ascii"):
        return
    if supplied.lower() == digest.hex():
        return
    raise SwordFault("EVMD5")
