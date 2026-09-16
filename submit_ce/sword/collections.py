"""SWORD collections, and which ones a depositor may post to.

A SWORD *collection* is an arXiv **group**, not an archive: ``/sword-app/cs-collection``
is ``grp_cs`` (``AtomPP.pm:221-236``). Permission comes from the
``arXiv_demographics.flag_group_*`` columns, the same flags the interactive
registration page sets (``AtomPP.pm:555-573``) -- *not* from endorsements, which is
what `SubmitApi.categories_for_user` reports.
"""

from dataclasses import dataclass
from typing import List, Optional

import arxiv.db.models as models
from arxiv.taxonomy.definitions import CATEGORIES, GROUPS
from sqlalchemy import select
from sqlalchemy.orm import Session as SqlalchemySession

from submit_ce.sword.atom import ns

GROUP_PREFIX = "grp_"

EXCLUDED_GROUPS = frozenset({"grp_bad"})
"""``grp_bad`` is a synthetic marker for unresolvable archives, not a real group.

It also has no ``flag_group_bad`` column, so it could never be permitted anyway.
"""


@dataclass(frozen=True)
class CategoryTerm:
    """One ``<category>`` / ``<arxiv:primary_category>`` entry."""

    term: str
    scheme: str
    label: str


def collection_name(group_id: str) -> str:
    """``grp_q-bio`` -> ``q-bio``, the name used in the collection URL."""
    return group_id[len(GROUP_PREFIX):] if group_id.startswith(GROUP_PREFIX) else group_id


def group_id(collection: str) -> str:
    """``q-bio`` -> ``grp_q-bio``."""
    return f"{GROUP_PREFIX}{collection}"


def demographic_flag(group_id_: str) -> str:
    """Column on ``arXiv_demographics`` holding permission for a group.

    ``grp_q-bio`` -> ``flag_group_q_bio``: hyphens become underscores, which is
    the ``s/-/_/g`` at ``AtomPP.pm:560``.
    """
    return f"flag_group_{collection_name(group_id_).replace('-', '_')}"


def known_groups() -> List[str]:
    """Every real group id, sorted."""
    return sorted(gid for gid in GROUPS if gid not in EXCLUDED_GROUPS)


def is_valid_collection(collection: str) -> bool:
    """Whether ``<collection>-collection`` names a real group.

    A miss is EVCOL (``AtomPP.pm:232-236``).
    """
    return group_id(collection) in set(known_groups())


def groups_for_user(session: SqlalchemySession, user_id: int) -> List[str]:
    """Group ids the user may deposit to, from their demographic flags.

    Returns ids (``grp_cs``), not collection names. Empty when the user has no
    demographics row.
    """
    demographics = session.get(models.Demographic, user_id)
    if demographics is None:
        return []
    return [gid for gid in known_groups()
            if getattr(demographics, demographic_flag(gid), 0)]


def collections_for_user(session: SqlalchemySession, user_id: int) -> List[str]:
    """`groups_for_user` as collection names."""
    return [collection_name(gid) for gid in groups_for_user(session, user_id)]


def user_may_post_to(session: SqlalchemySession, user_id: int,
                     collection: str) -> bool:
    """Whether the user holds the flag for ``collection``.

    Legacy matched the collection name against the group list with a regex
    (``AtomPP.pm:222``), so ``cs`` also matched ``grp_cs`` by substring. This
    compares exactly, which rejects a few nonsense values legacy would have let
    through.
    """
    return group_id(collection) in set(groups_for_user(session, user_id))


def endorsement_wildcards(session: SqlalchemySession,
                          user_id: int) -> List[str]:
    """Endorsements implied by a depositor's group flags.

    submit-ce gates `SetPrimaryClassification` on the creator being endorsed for
    the category (``domain/event/__init__.py:311-323``). Legacy SWORD has no such
    check: deposit permission *is* the ``flag_group_*`` bit, granted per collection
    by arXiv admins alongside ``flag_xml``/``flag_proxy``
    (``submit_sword.md:98-101``). Requiring personal endorsements as well would be
    stricter than legacy and would break exactly the proxy depositors -- conference
    organisers, journal editors -- that ``flag_proxy`` exists to accommodate.

    So each permitted group becomes ``<archive>.*`` for every archive it contains,
    which is the same permission expressed in the vocabulary the events understand.
    An ``<archive>.*`` wildcard also covers archives whose category *is* the archive
    (``hep-ex``), because the check resolves the category's archive first.

    Secondary classifications are not endorsement-checked at all, so cross-listing
    outside a depositor's groups keeps working, as it did in legacy.
    """
    wildcards = []
    for group in groups_for_user(session, user_id):
        for archive in GROUPS[group].get_archives():
            wildcards.append(f"{archive.id}.*")
    return sorted(set(wildcards))


def nickname_to_user_id(session: SqlalchemySession,
                        nickname: str) -> Optional[int]:
    """Resolve a tapir nickname to a user id.

    Case-sensitive, per ``submit_sword.md:726-727``. sqlite compares strings
    case-sensitively by default; MySQL's collation may not, so the comparison is
    re-checked in Python.
    """
    row = session.execute(
        select(models.TapirNickname)
        .where(models.TapirNickname.nickname == nickname)
    ).scalars().first()
    if row is None or row.nickname != nickname:
        return None
    return row.user_id


# ------------------------------------------------------------------ categories


def _subject_classes(archive) -> list:
    """Categories of ``archive`` that are subject classes (``archive.SC``).

    The ``test`` archive's categories are all flagged inactive in the taxonomy,
    but they are exactly what the SWORD test collection exists to exercise -- the
    live regression suite asserts ``test.dis-nn`` appears in the service document
    (``arxiv-test-regression/pytest/tests/test_sword.py:67``). So inactive
    categories are included for the test group only.
    """
    include_inactive = archive.in_group == "grp_test"
    categories = archive.get_categories(include_inactive=include_inactive)
    return sorted((category for category in categories if "." in category.id),
                  key=lambda category: category.id)


def categories_for_group(group_id_: str) -> List[CategoryTerm]:
    """Category terms advertised for one collection.

    Mirrors ``ServiceDoc.pm:186-231``: an archive with subject classes contributes
    one entry per class, labelled ``"<Group> - <Category>"``; an archive without
    them contributes the bare archive id, labelled with the archive's own name.

    This is the collection's **own** categories. ``ServiceDoc.pm:147-151`` handed
    every non-test collection the categories of *all* groups, which is a bug; per
    the plan's decision 1 it is not reproduced.
    """
    group = GROUPS.get(group_id_)
    if group is None:
        return []

    terms: List[CategoryTerm] = []
    # get_archives() already excludes defunct archives, which is exactly the
    # %IN_GROUP_NOT_DEFUNCT set legacy iterated (ServiceDoc.pm:189). There are
    # plenty of them -- acc-phys, chao-dyn, q-alg, supr-con and a dozen more.
    for archive in sorted(group.get_archives(), key=lambda a: a.id):
        classes = _subject_classes(archive)
        if classes:
            terms.extend(
                CategoryTerm(term=ns.ARXIV_SCHEME + category.id,
                             scheme=ns.ARXIV_SCHEME,
                             label=f"{group.full_name} - {category.full_name}")
                for category in classes)
        else:
            terms.append(
                CategoryTerm(term=ns.ARXIV_SCHEME + archive.id,
                             scheme=ns.ARXIV_SCHEME,
                             label=archive.full_name))
    terms.extend(_classification_scheme_terms(group_id_))
    return terms


def _classification_scheme_terms(group_id_: str) -> List[CategoryTerm]:
    """ACM and MSC placeholders (``ServiceDoc.pm:233-251``).

    Not real categories: they advertise that the CS and Maths collections accept
    an ACM or MSC class in a ``<category>`` whose scheme says so. The available
    terms are deliberately not enumerated (``submit_sword.md:260``).
    """
    if group_id_ == "grp_cs":
        return [CategoryTerm(
            term=ns.ACM_SCHEME + "/'select from list of ACM1998 classes'",
            scheme=ns.ACM_SCHEME,
            label="The ACM Computing Classification System")]
    if group_id_ == "grp_math":
        return [CategoryTerm(
            term=ns.MSC_SCHEME + "/'select from list of MSC2000 classes'",
            scheme=ns.MSC_SCHEME,
            label="Mathematics Subject Classification")]
    return []


def group_title(group_id_: str) -> str:
    """Collection title, ``"The <Group> archive"`` (``ServiceDoc.pm:132``)."""
    group = GROUPS.get(group_id_)
    return f"The {group.full_name} archive" if group else group_id_


def group_abstract(group_id_: str, main_site: str) -> str:
    """``dcterms:abstract`` for a collection (``ServiceDoc.pm:129``)."""
    group = GROUPS.get(group_id_)
    name = group.full_name if group else group_id_
    return f"The {name} e-print archive at http://{main_site}/"


def is_general_category(category_id: str) -> bool:
    """Whether a category is a general/'Other' one.

    ``physics.gen-ph``, ``math.GM``, ``cs.OH``, ``q-bio.OT``, ``econ.GN`` --
    identical between `arxiv.taxonomy` and ``Categories.pm:1128-1135``. Used by
    the cross-list rules (EGCTS/EGCCS).
    """
    category = CATEGORIES.get(category_id)
    return bool(category and category.is_general)
