"""Optional elements of the media response entry.

The route tests cover the common shapes; these pin the individual conditionals in
``AtomPP.pm:1400-1446``, where each optional element appears only when its input
is present.
"""

from datetime import datetime, timezone

from lxml import etree

from submit_ce.sword.atom import ns
from submit_ce.sword.atom.render import render_media_entry

MOMENT = datetime(2008, 5, 6, 16, 52, 58, tzinfo=timezone.utc)

BASE = dict(
    deposit_id="08050001",
    depositor="schwande",
    content_type="application/zip",
    collection="physics",
    group_name="Physics",
    base_url="https://arxiv.org",
    timestamp=MOMENT,
)


def _tree(**overrides):
    return etree.fromstring(render_media_entry(**{**BASE, **overrides}))


def test_no_contributor_without_a_mediated_user():
    assert _tree().find(ns.qname(ns.ATOM, "contributor")) is None


def test_contributor_with_only_a_name():
    contributor = _tree(contact_name="A. Scientist").find(
        ns.qname(ns.ATOM, "contributor"))
    assert contributor.findtext(ns.qname(ns.ATOM, "name")) == "A. Scientist"
    assert contributor.find(ns.qname(ns.ATOM, "email")) is None


def test_contributor_with_only_an_email():
    """A bare ``X-On-Behalf-Of`` address yields an empty display name."""
    contributor = _tree(contact_email="a@example.org").find(
        ns.qname(ns.ATOM, "contributor"))
    assert contributor.find(ns.qname(ns.ATOM, "name")) is None
    assert contributor.findtext(ns.qname(ns.ATOM, "email")) == "a@example.org"


def test_contributor_with_both():
    contributor = _tree(contact_name="A. Scientist",
                        contact_email="a@example.org").find(
        ns.qname(ns.ATOM, "contributor"))
    assert contributor.findtext(ns.qname(ns.ATOM, "name")) == "A. Scientist"
    assert contributor.findtext(ns.qname(ns.ATOM, "email")) == "a@example.org"


def test_packaging_and_user_agent_absent_by_default():
    root = _tree()
    assert root.find(ns.qname(ns.SWORD, "packaging")) is None
    assert root.find(ns.qname(ns.SWORD, "userAgent")) is None


def test_no_op_defaults_to_false():
    """The element is always present, unlike packaging and userAgent."""
    assert _tree().findtext(ns.qname(ns.SWORD, "noOp")) == "false"


def test_entry_matches_the_manual_example_ordering():
    """submit_sword.md:909-931, allowing the two documented deviations.

    The manual renders namespaces as https and shows generator version 0.9; the
    code has always emitted http and 1.1.
    """
    root = _tree(packaging="http://purl.org/net/sword-types/bagit",
                 user_agent="arXiv SWORD demo 1.1")
    tags = [etree.QName(child).localname for child in root]
    assert tags == ["author", "title", "id", "updated", "content", "source",
                    "summary", "treatment", "noOp", "packaging", "userAgent",
                    "primary_category", "link", "link"]


# ---------------------------------------------------- wrapper entry conditionals


def test_wrapper_entry_optional_elements():
    """The wrapper variant's own conditionals (AtomPP.pm:1400-1446)."""
    from submit_ce.sword.atom.render import render_wrapper_entry

    def tree(**kwargs):
        return etree.fromstring(render_wrapper_entry(
            deposit_id="08050007", depositor="schwande", summary="An abstract",
            primary_category="hep-th", base_url="https://arxiv.org",
            timestamp=MOMENT,
            **kwargs))

    plain = tree()
    assert plain.find(ns.qname(ns.ATOM, "contributor")) is None
    assert plain.find(ns.qname(ns.SWORD, "packaging")) is None
    assert plain.find(ns.qname(ns.SWORD, "userAgent")) is None
    assert plain.find(ns.qname(ns.SWORD, "verboseDescription")) is None

    name_only = tree(contact_name="A. Scientist")
    contributor = name_only.find(ns.qname(ns.ATOM, "contributor"))
    assert contributor.findtext(ns.qname(ns.ATOM, "name")) == "A. Scientist"
    assert contributor.find(ns.qname(ns.ATOM, "email")) is None

    email_only = tree(contact_email="a@example.org")
    contributor = email_only.find(ns.qname(ns.ATOM, "contributor"))
    assert contributor.find(ns.qname(ns.ATOM, "name")) is None
    assert contributor.findtext(ns.qname(ns.ATOM, "email")) == "a@example.org"

    extras = tree(packaging="http://purl.org/net/sword-types/bagit",
                  user_agent="arXiv SWORD demo 1.1")
    assert extras.findtext(ns.qname(ns.SWORD, "packaging"))
    assert extras.findtext(ns.qname(ns.SWORD, "userAgent"))


def test_replacement_verbose_description_differs():
    """AtomPP.pm:1382 picks a different string for a replacement."""
    from submit_ce.sword.atom.render import render_wrapper_entry

    def described(replacing):
        root = etree.fromstring(render_wrapper_entry(
            deposit_id="08050007", depositor="schwande", summary="An abstract",
            primary_category="hep-th", base_url="https://arxiv.org",
            timestamp=MOMENT,
            verbose=True, replacing=replacing))
        return root.findtext(ns.qname(ns.SWORD, "verboseDescription"))

    assert described(False) == "release pending"
    assert described(True) == "replacement being processed"
