"""A SWORD depositor client for tests.

Ports ``arxiv-lib/t/lib/Test/Sword.pm``: builds the requests a real depositor
sends, and pulls the interesting links back out of the response entry.

Credentials are always passed in. The Perl original hardcoded a live test account
(``02-deposit.t:44``, ``03-cross.t:34-35``, ``04-suspect.t:27``); that is
deliberately not carried over.

The request-building helpers are plain functions so they can be tested without a
server. `SwordClient` composes them onto anything with a ``post`` method taking
``(url, content=..., headers=...)`` -- a FastAPI ``TestClient`` or a stub.
"""

import base64
import hashlib
from dataclasses import dataclass
from typing import Any, Optional

from lxml import etree

from submit_ce.sword.atom import ns

USER_AGENT = "arXiv SWORD demo 1.1"
"""Test::Sword.pm:38. Echoed back in ``<sword:userAgent>``."""

ATOM_ENTRY_TYPE = "application/atom+xml;type=entry"
"""Content-Type that marks a POST as a metadata wrapper rather than media."""


def content_md5(payload: bytes) -> str:
    """Value for the ``Content-MD5`` header.

    Perl's ``md5_base64`` omits padding, which is why Test::Sword.pm:105 appends
    ``'=='``; the stdlib form already includes it, so the two agree. The live
    regression suite builds it this way too
    (``arxiv-test-regression/pytest/tests/test_sword.py:103``).

    The server accepts either this or lowercase hex (``AtomPP.pm:1501-1510``).
    """
    return base64.b64encode(hashlib.md5(payload).digest()).decode("ascii")


def content_md5_hex(payload: bytes) -> str:
    """Lowercase-hex alternative the server also accepts (``AtomPP.pm:1507``)."""
    return hashlib.md5(payload).hexdigest()


def deposit_headers(*,
                    content_type: str,
                    md5: Optional[str] = None,
                    on_behalf_of: Optional[str] = None,
                    verbose: bool = False,
                    no_op: bool = False,
                    packaging: Optional[str] = None,
                    user_agent: Optional[str] = USER_AGENT) -> dict:
    """Assemble deposit request headers, matching Test::Sword.pm:96-110.

    Optional headers are omitted entirely when unset, rather than sent empty --
    ``X-No-Op`` in particular is enabled by *any* value except the literal
    ``"false"`` (``AtomPP.pm:896-901``), so an empty one would switch it on.
    """
    headers = {"Content-Type": content_type}
    if user_agent is not None:
        headers["User-Agent"] = user_agent
    if md5 is not None:
        headers["Content-MD5"] = md5
    if on_behalf_of is not None:
        headers["X-On-Behalf-Of"] = on_behalf_of
    if verbose:
        headers["X-Verbose"] = "True"
    if no_op:
        headers["X-No-Op"] = "True"
    if packaging is not None:
        headers["X-Packaging"] = packaging
    return headers


def basic_auth(username: str, password: str) -> str:
    """An HTTP Basic ``Authorization`` value.

    Realm is ``SWORD at arXiv`` and the username is the tapir nickname,
    case-sensitively (``submit_sword.md:726-727``).
    """
    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return f"Basic {token}"


# ------------------------------------------------------------ response parsing


def _link_href(document: bytes, rel: str) -> Optional[str]:
    root = etree.fromstring(document)
    for link in root.iter(ns.qname(ns.ATOM, "link")):
        if link.get("rel") == rel:
            return link.get("href")
    return None


def edit_media_link(document: bytes) -> Optional[str]:
    """``rel="edit-media"`` href -- how a wrapper references deposited media.

    Test::Sword.pm:150 keeps this from every deposit response; it is the value
    that goes into the wrapper's ``rel="related"`` links.
    """
    return _link_href(document, "edit-media")


def edit_link(document: bytes) -> Optional[str]:
    """``rel="edit"`` href -- the PUT target for a replacement."""
    return _link_href(document, "edit")


def alternate_link(document: bytes) -> Optional[str]:
    """``rel="alternate"`` href -- the ``/resolve/app/<id>`` tracking URI."""
    return _link_href(document, "alternate")


def entry_id(document: bytes) -> Optional[str]:
    """The ``<id>``, e.g. ``info:arxiv/app/08050001``."""
    return etree.fromstring(document).findtext(ns.qname(ns.ATOM, "id"))


def sword_id(document: bytes) -> Optional[int]:
    """The numeric deposit id parsed out of ``<id>``.

    Mirrors ``test_sword.py:74-83``, which strips the ``info:arxiv/app/`` prefix.
    """
    identifier = entry_id(document)
    if not identifier:
        return None
    _, _, tail = identifier.rpartition("/")
    return int(tail) if tail.isdigit() else None


def error_code(document: bytes) -> Optional[int]:
    """The ``arxiv:errorcode`` from a ``<sword:error>`` document."""
    text = etree.fromstring(document).findtext(ns.qname(ns.ARXIV, "errorcode"))
    return int(text) if text else None


def error_summary(document: bytes) -> Optional[str]:
    """The human-readable ``<summary>`` of a ``<sword:error>`` document."""
    return etree.fromstring(document).findtext(ns.qname(ns.ATOM, "summary"))


@dataclass
class SwordClient:
    """Issues SWORD requests as one depositor.

    ``http`` is anything exposing ``post``/``get``/``put`` with httpx's signature.
    """

    http: Any
    username: str
    password: str
    base_url: str = "/sword-app"

    def _auth(self) -> dict:
        return {"Authorization": basic_auth(self.username, self.password)}

    def collection_url(self, collection: str) -> str:
        """``/sword-app/<collection>-collection`` (Test::Sword.pm:98)."""
        return f"{self.base_url}/{collection}-collection"

    def service_document(self, on_behalf_of: Optional[str] = None):
        headers = dict(self._auth())
        if on_behalf_of is not None:
            headers["X-On-Behalf-Of"] = on_behalf_of
        return self.http.get(f"{self.base_url}/servicedocument", headers=headers)

    def deposit_media(self, collection: str, payload: bytes, *,
                      content_type: str, md5: Optional[str] = None,
                      **header_kwargs):
        """POST a media resource to a collection."""
        headers = deposit_headers(content_type=content_type, md5=md5,
                                  **header_kwargs)
        headers.update(self._auth())
        return self.http.post(self.collection_url(collection),
                              content=payload, headers=headers)

    def deposit_wrapper(self, collection: str, wrapper_xml: bytes,
                        **header_kwargs):
        """POST a metadata wrapper to the same collection as its media."""
        headers = deposit_headers(content_type=ATOM_ENTRY_TYPE, **header_kwargs)
        headers.update(self._auth())
        return self.http.post(self.collection_url(collection),
                              content=wrapper_xml, headers=headers)

    def replace(self, edit_href: str, wrapper_xml: bytes, **header_kwargs):
        """PUT a wrapper to a ``rel="edit"`` href (``submit_sword.md:746-766``)."""
        headers = deposit_headers(content_type=ATOM_ENTRY_TYPE, **header_kwargs)
        headers.update(self._auth())
        return self.http.put(edit_href, content=wrapper_xml, headers=headers)
