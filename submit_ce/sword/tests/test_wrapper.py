"""The wrapper builder must emit what the server actually parses.

Every assertion here corresponds to something ``AtomPP.pm`` reads back off the
wrapper. The first four groups cover elements the legacy Perl helper emitted
malformed or not at all, so these paths had no coverage before -- see
`submit_ce.sword.tests.wrapper` for the list of defects.
"""

from lxml import etree

from submit_ce.sword.atom import ns
from submit_ce.sword.tests.wrapper import (
    Contributor,
    MediaLink,
    malformed_namespace_entry,
    wrapper_entry,
)

MINIMAL = dict(
    title="A strangely unique title",
    summary="A concise abstract of the important findings herein",
    primary_category="physics.class-ph",
    author_name="B. Editor",
)


def _tree(**overrides):
    return etree.fromstring(wrapper_entry(**{**MINIMAL, **overrides}))


def _texts(root, namespace, tag):
    return [element.text for element in root.iter(ns.qname(namespace, tag))]


# ------------------------------------------------------- structure and parsing


def test_root_is_an_atom_entry():
    root = _tree()
    assert root.tag == ns.qname(ns.ATOM, "entry")
    assert root.nsmap[None] == ns.ATOM
    assert root.nsmap["arxiv"] == ns.ARXIV


def test_document_is_well_formed_and_declares_utf8():
    assert wrapper_entry(**MINIMAL).startswith(b"<?xml")


def test_title_summary_and_id():
    root = _tree()
    assert root.findtext(ns.qname(ns.ATOM, "title")) == "A strangely unique title"
    assert root.findtext(ns.qname(ns.ATOM, "summary")).startswith("A concise abstract")
    assert root.findtext(ns.qname(ns.ATOM, "id")) == "arxiv:test::meta"


def test_author_is_the_depositing_account():
    root = _tree(author_name="B. Editor", author_email="editor@example.com")
    author = root.find(ns.qname(ns.ATOM, "author"))
    assert author.findtext(ns.qname(ns.ATOM, "name")) == "B. Editor"
    assert author.findtext(ns.qname(ns.ATOM, "email")) == "editor@example.com"


def test_author_email_omitted_when_absent():
    author = _tree().find(ns.qname(ns.ATOM, "author"))
    assert author.find(ns.qname(ns.ATOM, "email")) is None


def test_summary_can_be_made_too_short_for_the_ENSUM_boundary():
    """The server requires strictly more than 20 characters (AtomPP.pm:1088)."""
    twenty = "x" * 20
    root = _tree(summary=twenty)
    assert len(root.findtext(ns.qname(ns.ATOM, "summary"))) == 20


# ------------------------------------------------------------ categories


def test_primary_category_carries_the_scheme_prefixed_term():
    """AtomPP.pm:980 matches ``^{scheme}([-A-Za-z.]+)$``."""
    primary = _tree().find(ns.qname(ns.ARXIV, "primary_category"))
    assert primary.get("scheme") == "http://arxiv.org/terms/arXiv/"
    assert primary.get("term") == "http://arxiv.org/terms/arXiv/physics.class-ph"


def test_primary_label_is_optional():
    assert _tree().find(ns.qname(ns.ARXIV, "primary_category")).get("label") is None
    labelled = _tree(primary_label="Physics - Classical Physics")
    assert labelled.find(ns.qname(ns.ARXIV, "primary_category")).get("label") == \
        "Physics - Classical Physics"


def test_secondary_categories_are_atom_category_elements():
    root = _tree(categories=["physics.hist-ph", "cs.CG"])
    terms = [element.get("term")
             for element in root.iter(ns.qname(ns.ATOM, "category"))]
    assert terms == ["http://arxiv.org/terms/arXiv/physics.hist-ph",
                     "http://arxiv.org/terms/arXiv/cs.CG"]


def test_can_emit_enough_categories_to_trip_ENCTS():
    """Six categories is what 03-cross.t:119-123 sends to exceed the cap."""
    root = _tree(categories=["test.dis-nn", "test.mes-hall", "test.str-el",
                             "test.soft", "test.stat-mech", "test.supr-con"])
    assert len(list(root.iter(ns.qname(ns.ATOM, "category")))) == 6


# ------------------------------------------------------------- media links


def test_related_links_reference_deposited_media():
    root = _tree(links=[MediaLink("https://arxiv.org/sword-app/edit/08050001",
                                  "application/zip")])
    link = root.find(ns.qname(ns.ATOM, "link"))
    assert link.get("rel") == "related"
    assert link.get("href") == "https://arxiv.org/sword-app/edit/08050001"
    assert link.get("type") == "application/zip"


def test_multiple_media_links():
    root = _tree(links=[MediaLink("https://arxiv.org/sword-app/edit/08050001"),
                        MediaLink("https://arxiv.org/sword-app/edit/08050002",
                                  "application/pdf")])
    assert len(list(root.iter(ns.qname(ns.ATOM, "link")))) == 2


# ------------------------------------------------- contributors + affiliation


def test_contributors_are_the_arxiv_authors():
    root = _tree(contributors=[Contributor("A. Genius"),
                               Contributor("S. Clown", email="clown@example.com")])
    contributors = list(root.iter(ns.qname(ns.ATOM, "contributor")))
    assert len(contributors) == 2
    assert contributors[0].findtext(ns.qname(ns.ATOM, "name")) == "A. Genius"
    assert contributors[1].findtext(ns.qname(ns.ATOM, "email")) == "clown@example.com"


def test_contributor_affiliation_is_namespaced():
    """Never emitted by the Perl helper, so AtomPP.pm:940-942 was untested."""
    root = _tree(contributors=[
        Contributor("T. Tokunaga", affiliation="Kyoto Univ.")])
    contributor = root.find(ns.qname(ns.ATOM, "contributor"))
    affiliation = contributor.find(ns.qname(ns.ARXIV, "affiliation"))
    assert affiliation is not None, "affiliation must be in the arxiv namespace"
    assert affiliation.text == "Kyoto Univ."


def test_contributor_email_omitted_when_absent():
    root = _tree(contributors=[Contributor("A. Genius")])
    contributor = root.find(ns.qname(ns.ATOM, "contributor"))
    assert contributor.find(ns.qname(ns.ATOM, "email")) is None


# ----------------------------------------- repeatable arXiv extension elements


def test_arxiv_extension_elements_are_correctly_namespaced():
    """The four the Perl helper emitted malformed or unprefixed.

    ``report_no`` in particular went out with no ``arxiv:`` prefix, so it could
    never match ``getElementsByTagNameNS(ARXIVNS, 'report_no')``.
    """
    root = _tree(comments=["24 pages, 2 figures"],
                 journal_refs=["Nucl.Phys. B753 (2006) 295-312"],
                 dois=["10.1016/j.nuclphysb.2006.07.013"],
                 report_nums=["KUNS-2018"])

    assert _texts(root, ns.ARXIV, "comment") == ["24 pages, 2 figures"]
    assert _texts(root, ns.ARXIV, "journal_ref") == ["Nucl.Phys. B753 (2006) 295-312"]
    assert _texts(root, ns.ARXIV, "doi") == ["10.1016/j.nuclphysb.2006.07.013"]
    assert _texts(root, ns.ARXIV, "report_no") == ["KUNS-2018"]


def test_report_no_is_not_in_the_default_namespace():
    """Regression guard for defect 3 in the Perl helper."""
    root = _tree(report_nums=["KUNS-2018"])
    assert root.find(ns.qname(ns.ATOM, "report_no")) is None
    assert root.find(ns.qname(ns.ARXIV, "report_no")) is not None


def test_repeated_extension_elements_are_all_emitted():
    """The server joins multiples with ", " (AtomPP.pm:1163-1168)."""
    root = _tree(report_nums=["KUNS-2018", "YITP-06-19"])
    assert _texts(root, ns.ARXIV, "report_no") == ["KUNS-2018", "YITP-06-19"]


def test_extension_elements_absent_when_not_supplied():
    root = _tree()
    for tag in ("comment", "journal_ref", "doi", "report_no"):
        assert root.find(ns.qname(ns.ARXIV, tag)) is None, tag


# ----------------------------------------------------------------- xhtml content


def test_content_div_uses_the_correct_xhtml_namespace():
    """The Perl helper misspelled it ``xhmtl`` (defect 5)."""
    root = _tree()
    content = root.find(ns.qname(ns.ATOM, "content"))
    assert content.get("type") == "xhtml"
    div = content.find("{http://www.w3.org/1999/xhtml}div")
    assert div is not None
    assert div.text == "SWORD/APP arXiv submission wrapper"


# ------------------------------------------------------- negative fixture


def test_malformed_namespace_fixture_is_well_formed_but_unparseable_as_arxiv():
    """sample.xml's primary_category is invisible to a strict namespace match."""
    root = etree.fromstring(malformed_namespace_entry())

    # Well-formed XML, and it does have a title and contributor.
    assert root.findtext(ns.qname(ns.ATOM, "title"))
    assert root.find(ns.qname(ns.ATOM, "contributor")) is not None

    # But no primary_category in the real arXiv namespace -> ENPCT.
    assert root.find(ns.qname(ns.ARXIV, "primary_category")) is None
    assert not list(root.iter(ns.qname(ns.ARXIV, "primary_category")))


def test_malformed_namespace_fixture_lacks_the_trailing_slash():
    """The defect is subtle: capital X and a missing trailing slash."""
    document = malformed_namespace_entry()
    assert b'xmlns:arXiv="http://arxiv.org/schemas/atom"' in document
    assert ns.ARXIV.encode() not in document
