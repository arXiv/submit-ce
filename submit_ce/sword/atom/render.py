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
