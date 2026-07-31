"""Render SWORD response documents.

Currently the ``<sword:error>`` document. Service documents and deposit response
entries land with the routes that produce them, since both need collection and
deposit data that does not exist yet.

Element order matters: it is the order the legacy documents use
(``Error.pm:44-121``), and while no conforming client should depend on it,
byte-comparing against captures from the live service is how this port is
verified.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from lxml import etree

from submit_ce.sword.atom import ns
from submit_ce.sword.errors import SwordFault

ERROR_CONTENT_TYPE = "application/xml"
"""What legacy sets for error responses (``AtomPP.pm:1531``).

Note this is *not* ``application/atom+xml``, even though the body is an Atom
entry.
"""

ERROR_TREATMENT = "processing failed"


def iso_z(moment: datetime) -> str:
    """Format as ``2008-04-29T19:38:05Z``.

    Matches Perl's ``time2isoz()`` with the space swapped for a ``T``
    (``Error.pm:59``): UTC, second precision, no microseconds, ``Z`` suffix.
    """
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def render_error(fault: SwordFault,
                 *,
                 site: str,
                 main_site: Optional[str] = None,
                 timestamp: Optional[datetime] = None,
                 entry_id: Optional[str] = None) -> bytes:
    """Serialize ``fault`` as a ``<sword:error>`` document.

    Parameters
    ----------
    site
        Host this service answers as (Perl's ``$THIS_SITE``); used for the
        generator URI and for help anchors in some error hrefs.
    main_site
        Host for the human-facing help link (Perl's ``$MAIN_SITE``). Defaults to
        ``site``.
    timestamp, entry_id
        Injectable so output is deterministic under test.

    Notes
    -----
    ``entry_id`` defaults to a fresh UUID4. The Perl builds a *name-based* UUID
    from constant inputs (``Error.pm:57``), so every legacy error entry carries
    the same id -- which makes it useless for correlating a report with a log
    line, and contradicts the manual's own examples, which vary. A fresh id per
    error is the deliberate choice here.
    """
    main_site = main_site or site
    moment = timestamp or datetime.now(timezone.utc)

    root = etree.Element(ns.qname(ns.SWORD, "error"), nsmap=ns.NSMAP)
    root.set("href", fault.error.href(site))

    author = etree.SubElement(root, ns.qname(ns.ATOM, "author"))
    etree.SubElement(author, ns.qname(ns.ATOM, "name")).text = ns.ERROR_AUTHOR_NAME

    etree.SubElement(root, ns.qname(ns.ATOM, "title")).text = "ERROR"
    etree.SubElement(root, ns.qname(ns.ATOM, "id")).text = \
        f"info:arxiv/{entry_id or uuid.uuid4()}"
    etree.SubElement(root, ns.qname(ns.ATOM, "updated")).text = iso_z(moment)

    source = etree.SubElement(root, ns.qname(ns.ATOM, "source"))
    generator = etree.SubElement(source, ns.qname(ns.ATOM, "generator"))
    generator.text = ns.GENERATOR_NAME
    # http, not https: Error.pm:63-64 uses http here, while the deposit response
    # entry uses https for the same URI (AtomPP.pm:1435). Legacy is inconsistent;
    # each document is reproduced as it actually is.
    generator.set("uri", f"http://{site}/sword-app/")
    generator.set("version", ns.GENERATOR_VERSION)

    etree.SubElement(root, ns.qname(ns.SWORD, "treatment")).text = ERROR_TREATMENT

    link = etree.SubElement(root, ns.qname(ns.ATOM, "link"))
    link.set("rel", "alternate")
    link.set("href", f"http://{main_site}/help")
    link.set("type", "text/html")

    etree.SubElement(root, ns.qname(ns.ARXIV, "errorcode")).text = str(fault.error.code)
    etree.SubElement(root, ns.qname(ns.ATOM, "summary")).text = fault.summary

    return etree.tostring(root, xml_declaration=True, encoding="utf-8",
                          pretty_print=True)


ENTRY_CONTENT_TYPE = "application/atom+xml;type=entry"
"""Content-Type of a deposit response (``AtomPP.pm:644,679``)."""

MEDIA_TITLE = "Accepted media deposit to arXiv"
MEDIA_TREATMENT = "stored in author's workspace"
MEDIA_VERBOSE = "stored as is"
"""Fixed strings from ``AtomPP.pm:1385-1388``."""


def render_media_entry(*,
                       deposit_id: str,
                       depositor: str,
                       content_type: str,
                       collection: str,
                       group_name: str,
                       site: str,
                       timestamp: Optional[datetime] = None,
                       contact_name: Optional[str] = None,
                       contact_email: Optional[str] = None,
                       no_op: bool = False,
                       verbose: bool = False,
                       packaging: Optional[str] = None,
                       user_agent: Optional[str] = None) -> bytes:
    """The media link entry returned by a successful media deposit.

    ``AtomPP.pm:1375-1484`` with ``wrapper`` unset. Element order is legacy's.

    The ``arxiv:primary_category`` here names the **collection**, not a real
    category: at media-deposit time the subject category is not yet known, which
    the manual calls out explicitly (``submit_sword.md:386``). Its text is the
    group's display name.

    Unlike the wrapper response this carries no ``rel="alternate"`` link -- there is
    nothing to track until a wrapper initiates ingestion.
    """
    moment = timestamp or datetime.now(timezone.utc)

    root = etree.Element(ns.qname(ns.ATOM, "entry"), nsmap=ns.NSMAP)

    author = etree.SubElement(root, ns.qname(ns.ATOM, "author"))
    etree.SubElement(author, ns.qname(ns.ATOM, "name")).text = depositor

    # The mediated user becomes a contributor (AtomPP.pm:1406-1416).
    if contact_email or contact_name:
        contributor = etree.SubElement(root, ns.qname(ns.ATOM, "contributor"))
        if contact_name:
            etree.SubElement(contributor, ns.qname(ns.ATOM, "name")).text = contact_name
        if contact_email:
            etree.SubElement(contributor, ns.qname(ns.ATOM, "email")).text = contact_email

    etree.SubElement(root, ns.qname(ns.ATOM, "title")).text = MEDIA_TITLE
    etree.SubElement(root, ns.qname(ns.ATOM, "id")).text = \
        f"info:arxiv/app/{deposit_id}"
    etree.SubElement(root, ns.qname(ns.ATOM, "updated")).text = iso_z(moment)

    content = etree.SubElement(root, ns.qname(ns.ATOM, "content"))
    content.set("type", content_type)
    content.set("src", f"https://{site}/sword-app/edit/{deposit_id}")

    source = etree.SubElement(root, ns.qname(ns.ATOM, "source"))
    generator = etree.SubElement(source, ns.qname(ns.ATOM, "generator"))
    generator.text = ns.GENERATOR_NAME
    # https here, unlike the error document's http (AtomPP.pm:1435 vs Error.pm:63).
    generator.set("uri", f"https://{site}/sword-app/")
    generator.set("version", ns.GENERATOR_VERSION)

    etree.SubElement(root, ns.qname(ns.ATOM, "summary")).text = (
        f'A media deposit of type "{content_type}" was stored in the '
        "author's workspace")

    etree.SubElement(root, ns.qname(ns.SWORD, "treatment")).text = MEDIA_TREATMENT
    if verbose:
        etree.SubElement(root, ns.qname(ns.SWORD, "verboseDescription")).text = \
            MEDIA_VERBOSE
    etree.SubElement(root, ns.qname(ns.SWORD, "noOp")).text = \
        "true" if no_op else "false"
    if packaging:
        etree.SubElement(root, ns.qname(ns.SWORD, "packaging")).text = packaging
    if user_agent:
        etree.SubElement(root, ns.qname(ns.SWORD, "userAgent")).text = user_agent

    primary = etree.SubElement(root, ns.qname(ns.ARXIV, "primary_category"))
    primary.set("scheme", ns.ARXIV_SCHEME)
    primary.set("term", ns.ARXIV_SCHEME + collection)
    primary.text = group_name

    edit_media = etree.SubElement(root, ns.qname(ns.ATOM, "link"))
    edit_media.set("rel", "edit-media")
    edit_media.set("href", f"https://{site}/sword-app/edit/{deposit_id}")

    edit = etree.SubElement(root, ns.qname(ns.ATOM, "link"))
    edit.set("rel", "edit")
    edit.set("href", f"https://{site}/sword-app/edit/{deposit_id}.atom")

    return etree.tostring(root, xml_declaration=True, encoding="utf-8",
                          pretty_print=True)


WRAPPER_TITLE = "Accepted deposit wrapper to arXiv"
WRAPPER_TREATMENT = "atom wrapper used to initiate ingestion into arXiv"
WRAPPER_VERBOSE_NEW = "release pending"
WRAPPER_VERBOSE_REPLACEMENT = "replacement being processed"
"""``AtomPP.pm:1379-1383``."""


def render_wrapper_entry(*,
                         deposit_id: str,
                         depositor: str,
                         summary: str,
                         primary_category: str,
                         site: str,
                         secondary_categories: Optional[list] = None,
                         timestamp: Optional[datetime] = None,
                         contact_name: Optional[str] = None,
                         contact_email: Optional[str] = None,
                         no_op: bool = False,
                         verbose: bool = False,
                         packaging: Optional[str] = None,
                         user_agent: Optional[str] = None,
                         replacing: bool = False) -> bytes:
    """The entry returned when a metadata wrapper initiates ingestion.

    ``AtomPP.pm:1375-1484`` with ``wrapper`` set. Differs from the media entry in
    four ways: the fixed strings, the summary is the submission's abstract, the
    ``arxiv:primary_category`` carries a real category and **no text**
    (``AtomPP.pm:1450-1462``), and there is a ``rel="alternate"`` tracking link.

    That alternate link is ``http``, not ``https``, while the sibling ``edit`` links
    on the same element are ``https`` (``AtomPP.pm:1477-1481``). Legacy is
    inconsistent; each is reproduced as it is.
    """
    moment = timestamp or datetime.now(timezone.utc)
    content_type = ENTRY_CONTENT_TYPE

    root = etree.Element(ns.qname(ns.ATOM, "entry"), nsmap=ns.NSMAP)

    author = etree.SubElement(root, ns.qname(ns.ATOM, "author"))
    etree.SubElement(author, ns.qname(ns.ATOM, "name")).text = depositor

    if contact_email or contact_name:
        contributor = etree.SubElement(root, ns.qname(ns.ATOM, "contributor"))
        if contact_name:
            etree.SubElement(contributor, ns.qname(ns.ATOM, "name")).text = contact_name
        if contact_email:
            etree.SubElement(contributor, ns.qname(ns.ATOM, "email")).text = contact_email

    etree.SubElement(root, ns.qname(ns.ATOM, "title")).text = WRAPPER_TITLE
    etree.SubElement(root, ns.qname(ns.ATOM, "id")).text = \
        f"info:arxiv/app/{deposit_id}"
    etree.SubElement(root, ns.qname(ns.ATOM, "updated")).text = iso_z(moment)

    content = etree.SubElement(root, ns.qname(ns.ATOM, "content"))
    content.set("type", content_type)
    content.set("src", f"https://{site}/sword-app/edit/{deposit_id}")

    source = etree.SubElement(root, ns.qname(ns.ATOM, "source"))
    generator = etree.SubElement(source, ns.qname(ns.ATOM, "generator"))
    generator.text = ns.GENERATOR_NAME
    generator.set("uri", f"https://{site}/sword-app/")
    generator.set("version", ns.GENERATOR_VERSION)

    etree.SubElement(root, ns.qname(ns.ATOM, "summary")).text = summary

    etree.SubElement(root, ns.qname(ns.SWORD, "treatment")).text = WRAPPER_TREATMENT
    if verbose:
        etree.SubElement(root, ns.qname(ns.SWORD, "verboseDescription")).text = (
            WRAPPER_VERBOSE_REPLACEMENT if replacing else WRAPPER_VERBOSE_NEW)
    etree.SubElement(root, ns.qname(ns.SWORD, "noOp")).text = \
        "true" if no_op else "false"
    if packaging:
        etree.SubElement(root, ns.qname(ns.SWORD, "packaging")).text = packaging
    if user_agent:
        etree.SubElement(root, ns.qname(ns.SWORD, "userAgent")).text = user_agent

    # No text content here, unlike the media entry's group name.
    primary = etree.SubElement(root, ns.qname(ns.ARXIV, "primary_category"))
    primary.set("scheme", ns.ARXIV_SCHEME)
    primary.set("term", ns.ARXIV_SCHEME + primary_category)

    for category in (secondary_categories or []):
        element = etree.SubElement(root, ns.qname(ns.ATOM, "category"))
        element.set("scheme", ns.ARXIV_SCHEME)
        element.set("term", ns.ARXIV_SCHEME + category)

    edit_media = etree.SubElement(root, ns.qname(ns.ATOM, "link"))
    edit_media.set("rel", "edit-media")
    edit_media.set("href", f"https://{site}/sword-app/edit/{deposit_id}")

    edit = etree.SubElement(root, ns.qname(ns.ATOM, "link"))
    edit.set("rel", "edit")
    edit.set("href", f"https://{site}/sword-app/edit/{deposit_id}.atom")

    alternate = etree.SubElement(root, ns.qname(ns.ATOM, "link"))
    alternate.set("rel", "alternate")
    alternate.set("href", f"http://{site}/resolve/app/{deposit_id}")

    return etree.tostring(root, xml_declaration=True, encoding="utf-8",
                          pretty_print=True)
