"""Collection <-> group mapping and per-user permissions.

A SWORD collection is an arXiv *group*, and permission comes from the
``arXiv_demographics.flag_group_*`` columns (``AtomPP.pm:221-236,555-573``).
"""

import arxiv.db.models as models
import pytest
from arxiv.db import Session

from submit_ce.sword import collections


# --------------------------------------------------------------- name mapping


@pytest.mark.parametrize("group_id,name", [
    ("grp_cs", "cs"),
    ("grp_physics", "physics"),
    ("grp_q-bio", "q-bio"),
    ("grp_test", "test"),
])
def test_collection_name_round_trips(group_id, name):
    assert collections.collection_name(group_id) == name
    assert collections.group_id(name) == group_id


@pytest.mark.parametrize("group_id,column", [
    ("grp_cs", "flag_group_cs"),
    ("grp_physics", "flag_group_physics"),
    ("grp_q-bio", "flag_group_q_bio"),
    ("grp_q-fin", "flag_group_q_fin"),
])
def test_demographic_flag_replaces_hyphens(group_id, column):
    """``s/-/_/g`` at AtomPP.pm:560."""
    assert collections.demographic_flag(group_id) == column


def test_every_known_group_has_a_demographic_column():
    """A group with no flag column could never be granted."""
    for group_id in collections.known_groups():
        assert hasattr(models.Demographic, collections.demographic_flag(group_id)), \
            group_id


def test_grp_bad_is_excluded():
    """It is a synthetic marker for unresolvable archives, not a real group."""
    assert "grp_bad" not in collections.known_groups()
    assert not collections.is_valid_collection("bad")


def test_known_collections_include_the_ones_the_manual_names():
    names = {collections.collection_name(g) for g in collections.known_groups()}
    assert {"physics", "cs", "math", "stat", "q-bio", "test"} <= names


def test_nlin_is_no_longer_a_collection():
    """Removed in 2012-12 and folded into physics (submit_sword.md:1070-1077)."""
    assert not collections.is_valid_collection("nlin")


def test_unknown_collection_is_invalid():
    assert not collections.is_valid_collection("foobar")


# ------------------------------------------------------------- user permissions


def test_groups_for_user_reads_the_flags(depositor):
    """The fixture grants physics, cs and test."""
    group_ids = collections.groups_for_user(Session, depositor.user_id)
    assert set(group_ids) == {"grp_physics", "grp_cs", "grp_test"}


def test_collections_for_user_returns_names(depositor):
    assert set(collections.collections_for_user(Session, depositor.user_id)) == \
        {"physics", "cs", "test"}


def test_user_may_post_only_to_granted_collections(depositor):
    assert collections.user_may_post_to(Session, depositor.user_id, "cs")
    assert not collections.user_may_post_to(Session, depositor.user_id, "math")


def test_user_may_post_to_rejects_substring_matches(depositor):
    """Legacy matched with a regex, so 'c' would have matched 'grp_cs'."""
    assert not collections.user_may_post_to(Session, depositor.user_id, "c")


def test_groups_for_user_is_empty_without_demographics(sword_db):
    assert collections.groups_for_user(Session, 999999) == []


def test_nickname_lookup(depositor):
    assert collections.nickname_to_user_id(Session, depositor.nickname) == \
        depositor.user_id


def test_nickname_lookup_is_case_sensitive(depositor):
    """submit_sword.md:726-727."""
    assert collections.nickname_to_user_id(Session, depositor.nickname.upper()) is None


def test_nickname_lookup_misses_return_none(sword_db):
    assert collections.nickname_to_user_id(Session, "nobody") is None


# ------------------------------------------------------------------ categories


def test_stat_collection_primary_categories_match_the_manual():
    """submit_sword.md:274-290 lists these terms and label style."""
    terms = collections.categories_for_group("grp_stat")
    by_term = {term.term: term for term in terms}

    for category in ("stat.AP", "stat.CO", "stat.ML", "stat.ME", "stat.TH"):
        key = f"http://arxiv.org/terms/arXiv/{category}"
        assert key in by_term, category
        assert by_term[key].scheme == "http://arxiv.org/terms/arXiv/"

    assert by_term["http://arxiv.org/terms/arXiv/stat.AP"].label == \
        "Statistics - Applications"


def test_archive_without_subject_classes_is_listed_bare():
    """hep-ex has no subject classes, so the term is the archive itself."""
    terms = {t.term: t for t in collections.categories_for_group("grp_physics")}
    hep_ex = terms["http://arxiv.org/terms/arXiv/hep-ex"]
    assert hep_ex.label == "High Energy Physics - Experiment"


def test_test_collection_includes_its_inactive_categories():
    """The live regression suite asserts test.dis-nn is advertised.

    Every ``test`` category is flagged inactive in the taxonomy, so this would be
    empty without the deliberate include_inactive for grp_test.
    """
    terms = {t.term for t in collections.categories_for_group("grp_test")}
    assert "http://arxiv.org/terms/arXiv/test.dis-nn" in terms
    assert "http://arxiv.org/terms/arXiv/test.mes-hall" in terms


def test_cs_collection_includes_the_acm_scheme_placeholder():
    """ServiceDoc.pm:233-241."""
    terms = collections.categories_for_group("grp_cs")
    acm = [t for t in terms if t.scheme == "http://arxiv.org/terms/ACM1998"]
    assert len(acm) == 1
    assert acm[0].label == "The ACM Computing Classification System"


def test_math_collection_includes_the_msc_scheme_placeholder():
    terms = collections.categories_for_group("grp_math")
    msc = [t for t in terms if t.scheme == "http://arxiv.org/terms/MSC2000"]
    assert len(msc) == 1
    assert msc[0].label == "Mathematics Subject Classification"


def test_physics_does_not_get_the_acm_placeholder():
    schemes = {t.scheme for t in collections.categories_for_group("grp_physics")}
    assert "http://arxiv.org/terms/ACM1998" not in schemes


def test_collections_advertise_only_their_own_categories():
    """ServiceDoc.pm:147-151 gave every collection all groups' categories."""
    cs_terms = {t.term for t in collections.categories_for_group("grp_cs")}
    stat_terms = {t.term for t in collections.categories_for_group("grp_stat")}

    assert "http://arxiv.org/terms/arXiv/stat.AP" in stat_terms
    assert "http://arxiv.org/terms/arXiv/stat.AP" not in cs_terms
    assert "http://arxiv.org/terms/arXiv/cs.CG" in cs_terms
    assert "http://arxiv.org/terms/arXiv/cs.CG" not in stat_terms


def test_unknown_group_has_no_categories():
    assert collections.categories_for_group("grp_nope") == []


@pytest.mark.parametrize("defunct", ["acc-phys", "chao-dyn", "supr-con"])
def test_defunct_archives_are_not_advertised(defunct):
    """Legacy iterated %IN_GROUP_NOT_DEFUNCT (ServiceDoc.pm:189).

    ``Group.get_archives()`` already excludes inactive archives, so this holds
    without an explicit filter -- but it is the behaviour that matters, so it is
    asserted rather than assumed.
    """
    terms = {t.term for t in collections.categories_for_group("grp_physics")}
    assert f"http://arxiv.org/terms/arXiv/{defunct}" not in terms


def test_active_archives_are_advertised():
    terms = {t.term for t in collections.categories_for_group("grp_physics")}
    assert "http://arxiv.org/terms/arXiv/hep-ex" in terms


# -------------------------------------------------------- general categories


@pytest.mark.parametrize("category", [
    "physics.gen-ph", "math.GM", "cs.OH", "q-bio.OT", "econ.GN",
])
def test_the_five_general_categories(category):
    """Identical set in arxiv.taxonomy and Categories.pm:1128-1135."""
    assert collections.is_general_category(category)


@pytest.mark.parametrize("category", ["cs.CG", "stat.AP", "hep-ex"])
def test_ordinary_categories_are_not_general(category):
    assert not collections.is_general_category(category)


def test_unknown_category_is_not_general():
    assert not collections.is_general_category("nope.NOPE")


def test_titles_and_abstracts():
    assert collections.group_title("grp_stat") == "The Statistics archive"
    assert collections.group_abstract("grp_stat", "arxiv.org") == \
        "The Statistics e-print archive at http://arxiv.org/"
