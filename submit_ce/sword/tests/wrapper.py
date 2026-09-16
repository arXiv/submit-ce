"""Build SWORD metadata wrapper entries for tests.

Ports ``arxiv-lib/t/lib/Test/Sword/Metadata.pm``. That helper is buggy in ways
that left parts of the legacy implementation with **no test coverage at all**, so
the bugs are fixed here rather than reproduced:

1. The repeatable arXiv elements were emitted as
   ``"<arxiv:$entry xmlns:arxiv=\\"$ARXIVNS\\>\\""`` -- malformed XML.
2. ``$entry =~ s/s$//`` mutated the loop variable (the *attribute name*) while
   iterating over it.
3. ``<report_no>`` was emitted with no ``arxiv:`` prefix, so it could never match
   ``getElementsByTagNameNS(ARXIVNS, 'report_no')`` (``AtomPP.pm:1163-1168``).
4. ``contributor`` never emitted ``arxiv:affiliation``, though the tests passed
   one in -- so the affiliation path at ``AtomPP.pm:940-942`` was never exercised
   either.
5. The xhtml div namespace was misspelled ``xhmtl``, and ``my $ATOMNS`` was
   declared twice.

Consequences of 1-4: extraction of ``comment``, ``journal_ref``, ``doi``,
``report_no`` and ``affiliation`` was never tested. This module emits all of them
correctly so they can be.
"""

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from lxml import etree

from submit_ce.sword.atom import ns

XHTML = "http://www.w3.org/1999/xhtml"

DEFAULT_ENTRY_ID = "arxiv:test::meta"
"""Test::Sword::Metadata.pm's default ``<id>``."""

WRAPPER_CONTENT_TEXT = "SWORD/APP arXiv submission wrapper"


@dataclass(frozen=True)
class Contributor:
    """One author of the deposited work.

    SWORD maps arXiv's *authors* onto repeated ``<contributor>``, while
    ``<author>`` is the depositing account. The contact email is taken from the
    first contributor that has one (``AtomPP.pm:945-952``).
    """

    name: str
    email: Optional[str] = None
    affiliation: Optional[str] = None


@dataclass(frozen=True)
class MediaLink:
    """A ``rel="related"`` reference to an already-deposited media resource."""

    href: str
    mimetype: str = "application/zip"


def _sub(parent, namespace: str, tag: str, text: Optional[str] = None):
    element = etree.SubElement(parent, ns.qname(namespace, tag))
    if text is not None:
        element.text = text
    return element


def wrapper_entry(*,
                  title: str,
                  summary: str,
                  primary_category: str,
                  author_name: str,
                  author_email: Optional[str] = None,
                  primary_label: Optional[str] = None,
                  contributors: Sequence[Contributor] = (),
                  categories: Sequence[str] = (),
                  links: Sequence[MediaLink] = (),
                  comments: Iterable[str] = (),
                  journal_refs: Iterable[str] = (),
                  dois: Iterable[str] = (),
                  report_nums: Iterable[str] = (),
                  entry_id: str = DEFAULT_ENTRY_ID,
                  updated: str = "2008-04-23T03:45:04Z") -> bytes:
    """Serialize a deposit wrapper entry.

    ``primary_category`` and ``categories`` take bare arXiv ids (``cs.CG``); the
    ``http://arxiv.org/terms/arXiv/`` scheme prefix is added, since that is what
    the server parses back off (``AtomPP.pm:980``).

    ``updated`` is emitted even though Test::Sword::Metadata.pm omits it: Atom
    requires it and real depositors send it. The server does not read it.

    Element order follows the Perl helper, so captures line up.
    """
    root = etree.Element(ns.qname(ns.ATOM, "entry"),
                         nsmap={None: ns.ATOM, "arxiv": ns.ARXIV})

    _sub(root, ns.ATOM, "title", title)
    _sub(root, ns.ATOM, "id", entry_id)
    _sub(root, ns.ATOM, "updated", updated)

    author = _sub(root, ns.ATOM, "author")
    _sub(author, ns.ATOM, "name", author_name)
    if author_email is not None:
        _sub(author, ns.ATOM, "email", author_email)

    content = _sub(root, ns.ATOM, "content")
    content.set("type", "xhtml")
    div = etree.SubElement(content, f"{{{XHTML}}}div", nsmap={None: XHTML})
    div.text = WRAPPER_CONTENT_TEXT

    _sub(root, ns.ATOM, "summary", summary)

    primary = _sub(root, ns.ARXIV, "primary_category")
    primary.set("scheme", ns.ARXIV_SCHEME)
    primary.set("term", ns.ARXIV_SCHEME + primary_category)
    if primary_label is not None:
        primary.set("label", primary_label)

    for category in categories:
        element = _sub(root, ns.ATOM, "category")
        element.set("term", ns.ARXIV_SCHEME + category)
        element.set("scheme", ns.ARXIV_SCHEME)

    for link in links:
        element = _sub(root, ns.ATOM, "link")
        element.set("href", link.href)
        element.set("type", link.mimetype)
        element.set("rel", "related")

    for contributor in contributors:
        element = _sub(root, ns.ATOM, "contributor")
        _sub(element, ns.ATOM, "name", contributor.name)
        if contributor.email is not None:
            _sub(element, ns.ATOM, "email", contributor.email)
        if contributor.affiliation is not None:
            # arxiv:affiliation, a child of contributor (AtomPP.pm:940).
            _sub(element, ns.ARXIV, "affiliation", contributor.affiliation)

    # Repeatable arXiv extension elements. The server joins multiples with
    # ", " (AtomPP.pm:1163-1168).
    for tag, values in (("comment", comments),
                        ("journal_ref", journal_refs),
                        ("doi", dois),
                        ("report_no", report_nums)):
        for value in values:
            _sub(root, ns.ARXIV, tag, value)

    return etree.tostring(root, xml_declaration=True, encoding="utf-8",
                          pretty_print=True)


def malformed_namespace_entry() -> bytes:
    """Reproduce ``arxiv-lib/t/arxiv_atompp/data/sample.xml``'s defects.

    That fixture declares ``xmlns:arXiv="http://arxiv.org/schemas/atom"`` -- capital
    X, and no trailing slash, so it does not match ``ARXIVNS`` -- and uses a bare
    ``term="test.dis-nn"`` with no scheme prefix. A server that matches namespaces
    strictly finds no primary category and answers ENPCT, which makes this a
    useful negative fixture rather than the happy-path one it was meant to be.
    """
    return b"""<?xml version="1.0" encoding="utf-8"?>
<entry xmlns="http://www.w3.org/2005/Atom">
  <title>Testing the SWORD interface - a strangely unique title</title>
  <author>
    <name>Testing Testing</name>
    <email>tester@example.org</email>
  </author>
  <contributor>
    <name>T. Testing</name>
    <email>tester@example.org</email>
  </contributor>
  <summary>A concise abstract of the important findings, long enough to pass the
  twenty character minimum imposed on summaries.</summary>
  <arXiv:primary_category xmlns:arXiv="http://arxiv.org/schemas/atom"
    scheme="http://arxiv.org/terms/arXiv/"
    label="Test - Test Disruptive Networks" term="test.dis-nn"/>
  <category term="test.dis-nn" scheme="http://arxiv.org/schemas/atom"/>
  <link href="https://arxiv.org/sword-app/edit/09120007" type="application/pdf" rel="related"/>
</entry>
"""
