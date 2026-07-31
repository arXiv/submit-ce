"""Render the SWORD service document.

Ports ``arxiv-lib/lib/arXiv/AtomPP/ServiceDoc.pm``. The document is per-depositor:
it lists only the collections that depositor may post to, with each collection's
categories (``submit_sword.md:182-188``).

Three deliberate differences from legacy, all following the plan's decisions:

* **Each collection advertises its own categories.** ``ServiceDoc.pm:147-151``
  gave every non-test collection the categories of *all* groups.
* **``maxUploadSize`` reflects the real limit**, derived from submit-ce's size
  policy rather than the stale 10000 kB literal.
* **``acceptPackaging`` advertises zip only.** Legacy also advertised
  ``datapub.dataconservancy.org/package``, whose handler is dead code and which
  now answers 415.

``docx`` stays in the accepted media types even though a ``docx`` deposit is
rejected with 415 (``AtomPP.pm:262-274`` has no handler for it). That mismatch is
legacy's and removing the advertisement is a separate change.
"""

from typing import List, Optional, Sequence

from lxml import etree

from submit_ce.domain.size_limits import SIZE_LIMIT_POLICY
from submit_ce.sword import collections as sword_collections
from submit_ce.sword.atom import ns

DCTERMS_NSMAP = {None: "http://www.w3.org/2007/app",
                 "atom": ns.ATOM,
                 "sword": ns.SWORD,
                 "dcterms": ns.DCTERMS,
                 "arxiv": ns.ARXIV}
"""APP is the default namespace; Atom is explicitly prefixed.

Matches the legacy document, whose ``<service>`` root is APP while its titles are
``<atom:title>`` (``submit_sword.md:217-234``).
"""

APP = "http://www.w3.org/2007/app"

ACCEPTED_MEDIA_TYPES: Sequence[str] = (
    "application/atom+xml;type=entry",
    "application/zip",
    "application/xml",
    "application/pdf",
    "application/postscript",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/xml",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/gif",
)
"""``ServiceDoc.pm:71-83``, in the same order."""

ACCEPT_PACKAGING: Sequence[str] = (
    "http://purl.org/net/sword-types/bagit",
)

COLLECTION_POLICY = "Open Access"
"""``$defaultpolicy`` at ``ServiceDoc.pm:69``."""

TREATMENT = "will be posted pending moderator approval"
"""``ServiceDoc.pm:128``."""

MEDIATION = "true"
WORKSPACE_TITLE = "arXiv"

SERVICE_DOCUMENT_CONTENT_TYPE = "application/atomsvc+xml"
"""``AtomPP.pm:364``."""


def max_upload_size_kb() -> int:
    """``<sword:maxUploadSize>`` in kB.

    Derived from submit-ce's own limit so the two cannot drift; legacy hardcoded
    10000 while its actual cap was ``CGI::POST_MAX`` of 10 MiB (``AtomPP.pm:9``),
    so it under-advertised by 240 kB.
    """
    return SIZE_LIMIT_POLICY.total_limit() // 1024


def _set(parent, namespace: str, tag: str, text: Optional[str] = None):
    element = etree.SubElement(parent, ns.qname(namespace, tag))
    if text is not None:
        element.text = text
    return element


def render_service_document(*,
                            group_ids: Sequence[str],
                            site: str,
                            main_site: Optional[str] = None) -> bytes:
    """Serialize the service document for a depositor.

    ``group_ids`` are the groups the depositor may post to, as returned by
    `submit_ce.sword.collections.groups_for_user`. An empty sequence yields a
    workspace with no collections, which is the honest answer for an account with
    no group flags -- legacy instead defaulted to *every* group with a warning
    (``ServiceDoc.pm:104-107``), which would have advertised collections the
    depositor could not use.
    """
    main_site = main_site or site

    service = etree.Element(f"{{{APP}}}service", nsmap=DCTERMS_NSMAP)

    _set(service, ns.SWORD, "version", ns.SWORD_VERSION)
    _set(service, ns.SWORD, "maxUploadSize", str(max_upload_size_kb()))
    _set(service, ns.SWORD, "verbose", "true")
    _set(service, ns.SWORD, "noOp", "true")

    workspace = etree.SubElement(service, f"{{{APP}}}workspace")
    _set(workspace, ns.ATOM, "title", WORKSPACE_TITLE)

    for group_id in group_ids:
        _add_collection(workspace, group_id, site=site, main_site=main_site)

    return etree.tostring(service, xml_declaration=True, encoding="utf-8",
                          pretty_print=True)


def _add_collection(workspace, group_id: str, *, site: str, main_site: str):
    collection = etree.SubElement(workspace, f"{{{APP}}}collection")
    name = sword_collections.collection_name(group_id)
    collection.set("href", f"https://{site}/sword-app/{name}-collection")

    _set(collection, ns.ATOM, "title", sword_collections.group_title(group_id))
    for media_type in ACCEPTED_MEDIA_TYPES:
        _set(collection, APP, "accept", media_type)

    _set(collection, ns.SWORD, "collectionPolicy", COLLECTION_POLICY)
    _set(collection, ns.DCTERMS, "abstract",
         sword_collections.group_abstract(group_id, main_site))
    _set(collection, ns.SWORD, "mediation", MEDIATION)
    _set(collection, ns.SWORD, "treatment", TREATMENT)
    for packaging in ACCEPT_PACKAGING:
        _set(collection, ns.SWORD, "acceptPackaging", packaging)

    terms = sword_collections.categories_for_group(group_id)
    _add_categories(collection, terms)
    _add_primary_categories(collection, terms)
    return collection


def _add_categories(collection, terms: List[sword_collections.CategoryTerm]):
    """Secondary classification: plain ``atom:category`` elements."""
    categories = etree.SubElement(collection, f"{{{APP}}}categories")
    categories.set("fixed", "yes")
    for term in terms:
        element = _set(categories, ns.ATOM, "category")
        element.set("term", term.term)
        element.set("scheme", term.scheme)
        element.set("label", term.label)


def _add_primary_categories(collection,
                            terms: List[sword_collections.CategoryTerm]):
    """Primary classification, in the arXiv namespace.

    ``<arxiv:primary_categories fixed="yes">`` wrapping ``<arxiv:primary_category>``
    elements -- the extension that distinguishes the one required primary category
    from optional secondaries (``submit_sword.md:246-269``, ``ServiceDoc.pm:174-183``).
    """
    wrapper = _set(collection, ns.ARXIV, "primary_categories")
    wrapper.set("fixed", "yes")
    for term in terms:
        element = _set(wrapper, ns.ARXIV, "primary_category")
        element.set("term", term.term)
        element.set("scheme", term.scheme)
        element.set("label", term.label)
