"""Parse and validate a SWORD metadata wrapper entry.

Ports ``_process_wrapper_entry`` (``AtomPP.pm:924-1231``). The order of checks is
legacy's and is load-bearing: a wrapper with both an invalid category *and* a short
summary reports the category error, because categories are validated first.

Deliberately free of I/O so the whole ladder is unit-testable. The two things that
need the outside world are injected:

* ``is_suspect_email`` -- `submit_ce.sword.auth.is_suspect_email`
* ``deposit_extensions`` / ``deposit_owner`` -- `submit_ce.sword.deposits.DepositStore`

Error codes, in the order they can be raised: EVXML, ENCML, EVCML, ENPCT/EVPCT/EMPCT,
EVCTS/ENCTS/ERCTS/EGCTS/EGCCS, ENSUM, EVLNK/ELKTP/ENMDI/ENREL/ENMDE, ENOWN.
"""

import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence

from arxiv.taxonomy.definitions import ARCHIVES, CATEGORIES
from lxml import etree

from submit_ce.sword.atom import ns
from submit_ce.sword.errors import SwordFault

MINIMUM_SUMMARY_LENGTH = 20
"""``AtomPP.pm:1088`` compares ``length > 20``, so 20 exactly is too short."""

MAXIMUM_CATEGORIES = 5
"""Primary plus four secondaries (``AtomPP.pm:1047``, message says "4 secondary")."""

PRIMARY_TERM = re.compile(rf"^{re.escape(ns.ARXIV_SCHEME)}([-A-Za-z.]+)$")
"""``AtomPP.pm:980``. Anchored, and notably allows no digits -- no arXiv category
id contains one."""

SECONDARY_TERM = re.compile(rf"{re.escape(ns.ARXIV_SCHEME)}([-A-Za-z.]+)")
"""``AtomPP.pm:1018``. Unanchored, so it extracts from anywhere in the term."""

RELATED_HREF = re.compile(r"^https?://(?:\S+)/sword-app/edit/((\d{4})\d{4,})")
"""``AtomPP.pm:1102``."""

EXTENSION_ELEMENTS = ("comment", "journal_ref", "doi", "report_no")
"""Repeatable arXiv elements; multiples are joined with ", "
(``AtomPP.pm:1163-1168``)."""


def requires_subject_class(archive_id: str) -> bool:
    """Whether an archive's categories must name a subject class.

    Legacy consults ``%Subj_class_required`` (``Categories.pm:1172``). Here: an
    archive requires one when it has any dotted categories. Inactive ones count --
    every ``test.*`` category is flagged inactive, yet ``test`` alone is still not
    submittable.
    """
    archive = ARCHIVES.get(archive_id)
    if archive is None:
        return False
    return any("." in category.id
               for category in archive.get_categories(include_inactive=True))


def is_valid_category_strict(category_id: str) -> bool:
    """Port of ``is_valid_category_strict`` (``Categories.pm:1164-1178``).

    Rejects a trailing dot; a dotted id must exist; a **bare archive name is valid
    only when that archive has no subject classes**. That last clause is what makes
    ``cond-mat`` invalid while ``hep-ex`` is fine -- the distinction ``03-cross.t``
    asserts on. Active/inactive is deliberately not consulted: ``test.dis-nn`` is
    inactive in the taxonomy but is exactly what the test collection deposits.
    """
    if not category_id or category_id.endswith("."):
        return False
    if category_id not in CATEGORIES:
        return False
    if "." in category_id:
        return True
    return not requires_subject_class(category_id)


def canonical(category_id: str) -> str:
    """Resolve aliases, e.g. ``stat.TH`` -> ``math.ST`` (``canonicalize_category``)."""
    category = CATEGORIES.get(category_id)
    return category.canonical_id if category else category_id


def is_general(category_id: str) -> bool:
    """``physics.gen-ph``, ``math.GM``, ``cs.OH``, ``q-bio.OT``, ``econ.GN``."""
    category = CATEGORIES.get(category_id)
    return bool(category and category.is_general)


def archive_of(category_id: str) -> str:
    category = CATEGORIES.get(category_id)
    return category.in_archive if category else category_id.split(".", 1)[0]


def group_of(category_id: str) -> Optional[str]:
    """Group id owning a category, for the collection cross-check."""
    category = CATEGORIES.get(category_id)
    if category is None:
        return None
    return category.get_archive().in_group


@dataclass(frozen=True)
class WrapperMetadata:
    """A validated deposit wrapper, ready to become submission events."""

    title: str
    summary: str
    authors: List[str]
    contact_name: str
    contact_email: str
    primary_category: str
    categories: List[str] = field(default_factory=list)
    acm_class: Optional[str] = None
    msc_class: Optional[str] = None
    comments: Optional[str] = None
    journal_ref: Optional[str] = None
    doi: Optional[str] = None
    report_num: Optional[str] = None
    media_ids: List[str] = field(default_factory=list)

    @property
    def author_line(self) -> str:
        """Authors as arXiv stores them (``AtomPP.pm:1184``)."""
        return ", ".join(self.authors)

    @property
    def secondary_categories(self) -> List[str]:
        """``categories`` without the primary, which is stored first."""
        return [c for c in self.categories if c != self.primary_category]


def _text_of(element) -> str:
    return (element.text or "").strip()


def _child_text(parent, namespace: str, tag: str) -> str:
    return (parent.findtext(ns.qname(namespace, tag)) or "").strip()


def parse_document(document: bytes):
    """Parse bytes into an Atom entry element, or raise EVXML.

    ``AtomPP.pm:629-637`` answers EVXML when the body will not parse, and writes
    the unparsable text out for debugging.
    """
    try:
        root = etree.fromstring(document)
    except etree.XMLSyntaxError as exc:
        raise SwordFault(
            "EVXML",
            f"content could not be parsed as atom entry\n{exc}") from None
    if root.tag != ns.qname(ns.ATOM, "entry"):
        raise SwordFault("EVXML", "root element is not an atom entry")
    return root


def _collect_authors(root, is_suspect_email) -> tuple:
    """Contributors become the arXiv author list; the contact comes from them.

    ``AtomPP.pm:932-972``. A contributor with no name is skipped entirely. The
    contact address is the first *valid* email found, and its contributor's name
    becomes the contact name.
    """
    authors: List[str] = []
    contact_name = ""
    contact_email = ""

    for contributor in root.iter(ns.qname(ns.ATOM, "contributor")):
        name = _child_text(contributor, ns.ATOM, "name")
        if not name:
            continue

        affiliation = _child_text(contributor, ns.ARXIV, "affiliation")
        authors.append(f"{name} ({affiliation})" if affiliation else name)

        email = _child_text(contributor, ns.ATOM, "email")
        if email and not contact_email:
            contact_email = email
            contact_name = name

    if not contact_email:
        raise SwordFault("ENCML")

    if is_suspect_email(contact_email):
        raise SwordFault(
            "EVCML",
            "arXiv does not accept third party submission for author, "
            "they must submit directly")

    return authors, contact_name, contact_email


def _primary_category(root, collection: Optional[str],
                      replacing: bool) -> str:
    """Exactly one ``arxiv:primary_category``, valid, and in this collection.

    ``AtomPP.pm:977-1003``. The collection cross-check is skipped for a
    replacement, which is PUT to an ``edit`` href rather than posted to a
    collection.
    """
    nodes = list(root.iter(ns.qname(ns.ARXIV, "primary_category")))
    if len(nodes) > 1:
        raise SwordFault("EMPCT")
    if not nodes:
        raise SwordFault("ENPCT")

    match = PRIMARY_TERM.match(nodes[0].get("term") or "")
    term = match.group(1) if match else None
    if term is None or not is_valid_category_strict(term):
        raise SwordFault("EVPCT", f"no such primary category: '{term}'")

    if not replacing:
        if group_of(term) != f"grp_{collection}":
            raise SwordFault(
                "EVPCT",
                f"no primary category '{term}' in collection '{collection}'")

    return canonical(term)


def _scheme_classes(terms: Sequence[str], scheme: str) -> Optional[str]:
    """ACM/MSC classes carried in ``<category>`` terms of a given scheme.

    ``AtomPP.pm:1008-1015`` strips the scheme (and an optional ``/``) and joins
    multiples with ", ".
    """
    pattern = re.compile(rf"{re.escape(scheme)}/?(.*)")
    found = [pattern.match(term).group(1)
             for term in terms if term.startswith(scheme)]
    return ", ".join(found) if found else None


def _minimal_list(categories: Sequence[str]) -> List[str]:
    """Canonicalize and de-duplicate, preserving order.

    Stands in for ``arXiv::Categories->minimal_list``.
    """
    seen = []
    for category in categories:
        resolved = canonical(category)
        if resolved not in seen:
            seen.append(resolved)
    return seen


def _check_cross_list_rules(categories: Sequence[str], primary: str) -> None:
    """The three general-category rules (``AtomPP.pm:1052-1078``).

    Exercised by ``03-cross.t``; the expected messages are asserted there.
    """
    for category in categories:
        # physics.gen-ph may be a primary but never a cross.
        if category != primary and category == "physics.gen-ph":
            raise SwordFault("EVCTS", f"cross to '{category}' not allowed")

        # A general primary admits no crosses at all.
        if is_general(primary) and category != primary:
            raise SwordFault("EGCCS")

        # A general cross may not sit beside another category of its archive.
        if is_general(category) and category != primary:
            archive = archive_of(category)
            for other in categories:
                if other != category and archive_of(other) == archive:
                    raise SwordFault("EGCTS")


def _categories(root, primary: str, replacing: bool,
                existing_categories: Optional[Sequence[str]]) -> tuple:
    """Secondary classification, ACM/MSC classes, and the cross-list rules.

    ``AtomPP.pm:1005-1085``. The returned list is primary-first, matching the
    ``Categories`` field legacy builds at ``AtomPP.pm:1175-1180``.
    """
    terms = [element.get("term") or ""
             for element in root.iter(ns.qname(ns.ATOM, "category"))]
    if not terms:
        return [primary], None, None

    acm = _scheme_classes(terms, ns.ACM_SCHEME)
    msc = _scheme_classes(terms, ns.MSC_SCHEME)

    extracted = [match.group(1) for match in
                 (SECONDARY_TERM.search(term) for term in terms) if match]
    categories = [primary] + [c for c in extracted if c != primary]

    for category in categories:
        if not is_valid_category_strict(category):
            raise SwordFault("EVCTS", f"no such category: '{category}'")

    minimal = _minimal_list(categories)

    if replacing:
        if existing_categories is not None:
            if set(minimal) != set(_minimal_list(existing_categories)):
                raise SwordFault("ERCTS")
    else:
        if len(categories) > MAXIMUM_CATEGORIES:
            raise SwordFault("ENCTS")
        _check_cross_list_rules(minimal, primary)

    return categories, acm, msc


def _summary(root) -> str:
    """Abstract, which must exceed 20 characters (``AtomPP.pm:1087-1093``)."""
    summary = _child_text(root, ns.ATOM, "summary")
    if len(summary) <= MINIMUM_SUMMARY_LENGTH:
        raise SwordFault("ENSUM")
    return summary


def _media_ids(root, deposit_extensions, deposit_owner,
               depositor: Optional[str]) -> List[str]:
    """Deposit ids referenced by ``rel="related"`` links.

    ``AtomPP.pm:1095-1161``. A wrapper must reference at least one media deposit,
    and each referenced id must exist with the MIME type the link claims.

    Ownership is **enforced**, unlike legacy, which only warned -- and left a
    ``## FIXME: this should be fatal`` beside it (``AtomPP.pm:1126-1129``).
    Without the check a depositor can attach another user's staged files to their
    own submission.
    """
    from submit_ce.sword.deposits import extension_for_link

    media_ids: List[str] = []
    related = 0

    for link in root.iter(ns.qname(ns.ATOM, "link")):
        if link.get("rel") != "related":
            continue
        related += 1

        href = link.get("href") or ""
        match = RELATED_HREF.match(href)
        if not match:
            raise SwordFault("EVLNK", f"Is the link href valid? {href}")
        deposit_id = match.group(1)

        wanted = extension_for_link(link.get("type") or "")
        available = deposit_extensions(deposit_id)

        if wanted not in available:
            if len(available) == 1:
                raise SwordFault(
                    "ENMDI",
                    f"Media entry with id (info:arxiv/app/{deposit_id}) with "
                    f"specified MIME type could not be found. We have a media "
                    f"entry ({deposit_id}.{available[0]}) instead.")
            if len(available) > 1:
                raise SwordFault(
                    "ENMDI",
                    f"Media entry with id (info:arxiv/app/{deposit_id}) is "
                    "ambiguous. This should not happen. Please alert the "
                    "administrator of this server to this problem.")
            raise SwordFault("ENMDI", f"info:arxiv/app/{deposit_id}")

        if depositor is not None and deposit_owner(deposit_id) != depositor:
            raise SwordFault(
                "ENOWN",
                f"media entry info:arxiv/app/{deposit_id} belongs to "
                "another depositor")

        media_ids.append(deposit_id)

    if related == 0:
        raise SwordFault("ENREL")
    # Legacy follows this with `if (@files) {...} else { ENMDE }`
    # (``AtomPP.pm:1156-1161``), but that branch cannot be reached: every related
    # link either returns an error or appends a file, so the list is non-empty
    # whenever the count is. Not reproduced -- ENMDE stays in the code table for
    # completeness, it just has no live caller here.
    return media_ids


def _extension_elements(root) -> dict:
    """``arxiv:comment`` / ``journal_ref`` / ``doi`` / ``report_no``."""
    values = {}
    for tag in EXTENSION_ELEMENTS:
        found = [_text_of(element)
                 for element in root.iter(ns.qname(ns.ARXIV, tag))]
        values[tag] = ", ".join(v for v in found if v) if found else None
    return values


def parse_wrapper(document: bytes,
                  *,
                  collection: Optional[str] = None,
                  depositor: Optional[str] = None,
                  contact_override: Optional[tuple] = None,
                  is_suspect_email: Callable[[str], bool] = lambda _: False,
                  deposit_extensions: Callable[[str], List[str]] = lambda _: [],
                  deposit_owner: Callable[[str], Optional[str]] = lambda _: None,
                  replacing: bool = False,
                  existing_categories: Optional[Sequence[str]] = None,
                  ) -> WrapperMetadata:
    """Validate a wrapper entry and return its metadata.

    ``contact_override`` is the ``(name, email)`` from an ``X-On-Behalf-Of`` header,
    which takes precedence over the contributor list -- the header exists to
    disambiguate when several contributors carry an email
    (``submit_sword.md:518-527``).

    Raises `SwordFault` on the first failure, in legacy's order.
    """
    root = parse_document(document)

    if contact_override and contact_override[1]:
        contact_name, contact_email = contact_override
        authors, _, _ = _collect_authors_lenient(root)
        if is_suspect_email(contact_email):
            raise SwordFault(
                "EVCML",
                "arXiv does not accept third party submission for author, "
                "they must submit directly")
    else:
        authors, contact_name, contact_email = _collect_authors(
            root, is_suspect_email)

    primary = _primary_category(root, collection, replacing)
    categories, acm, msc = _categories(root, primary, replacing,
                                       existing_categories)
    summary = _summary(root)
    media_ids = _media_ids(root, deposit_extensions, deposit_owner, depositor)
    extensions = _extension_elements(root)

    return WrapperMetadata(
        # No check for a missing title: ENTIT is defined but AtomPP.pm:1183 uses
        # $entry->title() unvalidated, so an untitled wrapper is accepted.
        title=_child_text(root, ns.ATOM, "title"),
        summary=summary,
        authors=authors,
        contact_name=contact_name,
        contact_email=contact_email,
        primary_category=primary,
        categories=categories,
        acm_class=acm,
        msc_class=msc,
        comments=extensions["comment"],
        journal_ref=extensions["journal_ref"],
        doi=extensions["doi"],
        report_num=extensions["report_no"],
        media_ids=media_ids,
    )


def _collect_authors_lenient(root) -> tuple:
    """Author list only, without requiring a contact email.

    Used when ``X-On-Behalf-Of`` already supplied the contact, so ENCML does not
    apply (``AtomPP.pm:927-930`` shows legacy intended this, commented out).
    """
    authors: List[str] = []
    for contributor in root.iter(ns.qname(ns.ATOM, "contributor")):
        name = _child_text(contributor, ns.ATOM, "name")
        if not name:
            continue
        affiliation = _child_text(contributor, ns.ARXIV, "affiliation")
        authors.append(f"{name} ({affiliation})" if affiliation else name)
    return authors, "", ""
