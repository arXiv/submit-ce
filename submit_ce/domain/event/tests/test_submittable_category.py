"""Which categories a submission may be classified in.

`arxiv.taxonomy` uses one ``is_active`` flag for two different things -- "not a
current category" and "do not list this" -- and the ``test`` archive only wants the
second. See `is_submittable_category` for why ``test`` is named explicitly.
"""

import pytest

from submit_ce.domain.event.validators import (
    is_submittable_category,
    must_be_an_active_category,
)
from submit_ce.domain.exceptions import InvalidEvent


@pytest.mark.parametrize("category", [
    "cs.CG", "stat.AP", "physics.gen-ph", "math.ST", "hep-ex", "gr-qc",
])
def test_ordinary_active_categories_are_submittable(category):
    assert is_submittable_category(category)


@pytest.mark.parametrize("category", [
    "test.dis-nn", "test.mes-hall", "test.mtrl-sci", "test.soft",
    "test.stat-mech", "test.str-el", "test.supr-con",
])
def test_test_categories_are_submittable(category):
    """All seven are flagged inactive in the taxonomy, and all are depositable.

    The live SWORD regression suite deposits to ``test`` on non-dev environments
    (``arxiv-test-regression/pytest/tests/test_sword.py:94-99``).
    """
    assert is_submittable_category(category)


def test_bare_test_archive_is_not_submittable():
    """``$Subj_class_required{'test'} = 1`` -- a subject class is mandatory."""
    assert not is_submittable_category("test")


@pytest.mark.parametrize("category", [
    "cond-mat",   # bare archive whose categories are all subdivided
    "q-bio",
    "acc-phys",   # defunct archive
    "alg-geom",
    "chao-dyn",
])
def test_retired_and_bare_categories_stay_unsubmittable(category):
    """The change must not reopen defunct archives or bare archive names."""
    assert not is_submittable_category(category)


@pytest.mark.parametrize("category", ["", "nope.NOPE", "cs.", "test."])
def test_nonexistent_categories_are_not_submittable(category):
    assert not is_submittable_category(category)


def test_only_the_test_archive_is_special_cased():
    """Guards the narrowness of the exemption.

    If a real category is ever retired while its archive stays active, it must not
    become submittable as a side effect. Today ``test`` is the only archive with
    inactive subdivided categories; this fails if that stops being true without the
    validator being revisited.
    """
    from arxiv.taxonomy.definitions import ARCHIVES, CATEGORIES

    unexpected = {
        category.id for category in CATEGORIES.values()
        if not category.is_active
        and "." in category.id
        and category.in_archive != "test"
        and (ARCHIVES.get(category.in_archive) or None)
        and ARCHIVES[category.in_archive].is_active
    }
    assert unexpected == set(), (
        "these are inactive categories in active archives and are now silently "
        f"unsubmittable-or-not by rule rather than by name: {sorted(unexpected)}")


# ------------------------------------------------------- the event-level validator


@pytest.fixture
def event():
    """A real event: `InvalidEvent` reads ``event_type`` off it for the message."""
    from submit_ce.domain.agent import InternalClient, PublicUser
    from submit_ce.domain.event import SetPrimaryClassification

    creator = PublicUser(user_id="1", name="Test User",
                         email="tester@example.org")
    return SetPrimaryClassification(creator=creator,
                                    client=InternalClient(name="probe"))


def test_validator_accepts_a_test_category(event):
    must_be_an_active_category(event, "test.dis-nn", None)


def test_validator_accepts_an_ordinary_category(event):
    must_be_an_active_category(event, "cs.CG", None)


@pytest.mark.parametrize("category", ["cond-mat", "acc-phys", "nope.NOPE", ""])
def test_validator_rejects_unsubmittable_categories(event, category):
    with pytest.raises(InvalidEvent, match="Not a valid category"):
        must_be_an_active_category(event, category, None)


def test_validator_rejects_none(event):
    with pytest.raises(InvalidEvent):
        must_be_an_active_category(event, None, None)
