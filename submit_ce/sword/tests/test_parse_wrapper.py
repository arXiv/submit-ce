"""The wrapper validation ladder.

Ports the assertions of ``arxiv-lib/t/arxiv_atompp/03-cross.t`` and
``04-suspect.t``, plus the paths the legacy Perl helper's defects left untested at
all (extension elements, affiliations).

Order matters and is asserted: legacy validates categories before the summary, so
a wrapper wrong in both ways reports the category error.
"""

import pytest

from submit_ce.sword.atom.parse import (
    is_valid_category_strict,
    parse_wrapper,
    requires_subject_class,
)
from submit_ce.sword.errors import SwordFault
from submit_ce.sword.tests.wrapper import (
    Contributor,
    MediaLink,
    malformed_namespace_entry,
    wrapper_entry,
)

MEDIA_HREF = "https://arxiv.org/sword-app/edit/10030146"
GOOD_SUMMARY = "A concise abstract of the important findings herein"

BASE = dict(
    title="A strangely unique title",
    summary=GOOD_SUMMARY,
    primary_category="cs.CG",
    author_name="B. Editor",
    contributors=[Contributor("A. Genius", email="genius@example.org")],
    links=[MediaLink(MEDIA_HREF, "application/zip")],
)


def _parse(*, entry_kwargs=None, **kwargs):
    kwargs.setdefault("collection", "cs")
    kwargs.setdefault("depositor", "vtex")
    kwargs.setdefault("deposit_extensions", lambda _: ["zip"])
    kwargs.setdefault("deposit_owner", lambda _: "vtex")
    document = wrapper_entry(**{**BASE, **(entry_kwargs or {})})
    return parse_wrapper(document, **kwargs)


def _fault(entry_kwargs=None, **kwargs) -> SwordFault:
    with pytest.raises(SwordFault) as excinfo:
        _parse(entry_kwargs=entry_kwargs, **kwargs)
    return excinfo.value


# ------------------------------------------------------- is_valid_category_strict


@pytest.mark.parametrize("category", [
    "cs.CG", "stat.AP", "physics.gen-ph", "test.dis-nn", "hep-ex", "gr-qc",
])
def test_valid_categories(category):
    assert is_valid_category_strict(category)


@pytest.mark.parametrize("category", [
    "cond-mat",     # bare archive that requires a subject class -- 03-cross.t
    "q-bio",
    "test",
    "cs",
    "physics",
    "nope.NOPE",
    "cs.",
    "",
])
def test_invalid_categories(category):
    assert not is_valid_category_strict(category)


def test_inactive_subject_classes_are_still_valid():
    """Every test.* category is inactive, and all of them are depositable."""
    assert is_valid_category_strict("test.dis-nn")


def test_requires_subject_class():
    assert requires_subject_class("cond-mat")
    assert requires_subject_class("test")
    assert not requires_subject_class("hep-ex")
    assert not requires_subject_class("nope")


# -------------------------------------------------------------------- happy path


def test_minimal_wrapper_parses():
    metadata = _parse()
    assert metadata.title == "A strangely unique title"
    assert metadata.summary == GOOD_SUMMARY
    assert metadata.primary_category == "cs.CG"
    assert metadata.categories == ["cs.CG"]
    assert metadata.media_ids == ["10030146"]


def test_contributors_become_the_author_list():
    metadata = _parse(entry_kwargs={"contributors": [
        Contributor("A. Genius", email="genius@example.org"),
        Contributor("S. Clown"),
    ]})
    assert metadata.authors == ["A. Genius", "S. Clown"]
    assert metadata.author_line == "A. Genius, S. Clown"


def test_affiliation_is_appended_in_parentheses():
    """AtomPP.pm:940-942 -- a path the Perl test helper never exercised."""
    metadata = _parse(entry_kwargs={"contributors": [
        Contributor("T. Tokunaga", email="t@example.org",
                    affiliation="Kyoto Univ.")]})
    assert metadata.authors == ["T. Tokunaga (Kyoto Univ.)"]


def test_contact_comes_from_the_first_contributor_with_an_email():
    metadata = _parse(entry_kwargs={"contributors": [
        Contributor("No Email"),
        Contributor("First Email", email="first@example.org"),
        Contributor("Second Email", email="second@example.org"),
    ]})
    assert metadata.contact_email == "first@example.org"
    assert metadata.contact_name == "First Email"


def test_contributors_without_a_name_are_skipped():
    metadata = _parse(entry_kwargs={"contributors": [
        Contributor("", email="nameless@example.org"),
        Contributor("Real Name", email="real@example.org"),
    ]})
    assert metadata.authors == ["Real Name"]
    assert metadata.contact_email == "real@example.org"


def test_on_behalf_of_overrides_the_contributor_contact():
    """The header exists to disambiguate (submit_sword.md:518-527)."""
    metadata = _parse(contact_override=("A. Scientist", "scientist@example.org"))
    assert metadata.contact_email == "scientist@example.org"
    assert metadata.contact_name == "A. Scientist"
    assert metadata.authors == ["A. Genius"]


def test_on_behalf_of_makes_a_missing_contributor_email_acceptable():
    metadata = _parse(entry_kwargs={"contributors": [Contributor("A. Genius")]},
                      contact_override=("A. Scientist", "s@example.org"))
    assert metadata.contact_email == "s@example.org"


# -------------------------------------------------------------- contact failures


def test_no_contact_email_is_encml():
    fault = _fault({"contributors": [Contributor("A. Genius")]})
    assert fault.error.mnemonic == "ENCML"
    assert fault.summary == "No contact email"


def test_no_contributors_at_all_is_encml():
    assert _fault({"contributors": []}).error.mnemonic == "ENCML"


def test_suspect_contact_is_evcml():
    """04-suspect.t:96-100 -- errorcode 512 and 'must submit directly'."""
    fault = _fault(is_suspect_email=lambda email: email == "genius@example.org")
    assert fault.error.code == 512
    assert "must submit directly" in fault.summary


def test_suspect_on_behalf_of_contact_is_evcml():
    fault = _fault(contact_override=("S. Uspect", "suspect@example.org"),
                   is_suspect_email=lambda email: email == "suspect@example.org")
    assert fault.error.code == 512


# ------------------------------------------------------------- primary category


def test_missing_primary_category_is_enpct():
    """The malformed-namespace fixture is invisible to a strict match."""
    with pytest.raises(SwordFault) as excinfo:
        parse_wrapper(malformed_namespace_entry(), collection="test",
                      deposit_extensions=lambda _: ["pdf"])
    assert excinfo.value.error.mnemonic == "ENPCT"


def test_two_primary_categories_is_empct():
    document = wrapper_entry(**BASE).replace(
        b"</entry>",
        b'  <arxiv:primary_category term="http://arxiv.org/terms/arXiv/cs.AI"'
        b' scheme="http://arxiv.org/terms/arXiv/"/>\n</entry>')
    with pytest.raises(SwordFault) as excinfo:
        parse_wrapper(document, collection="cs", depositor="vtex",
                      deposit_extensions=lambda _: ["zip"],
                      deposit_owner=lambda _: "vtex")
    assert excinfo.value.error.mnemonic == "EMPCT"


def test_unknown_primary_category_is_evpct():
    fault = _fault({"primary_category": "nope.NOPE"})
    assert fault.error.mnemonic == "EVPCT"
    assert "no such primary category" in fault.summary


def test_bare_archive_primary_is_evpct():
    fault = _fault({"primary_category": "cond-mat"}, collection="physics")
    assert fault.error.mnemonic == "EVPCT"


def test_primary_category_must_belong_to_the_collection():
    """AtomPP.pm:983-991."""
    fault = _fault({"primary_category": "stat.AP"}, collection="cs")
    assert fault.error.mnemonic == "EVPCT"
    assert "no primary category 'stat.AP' in collection 'cs'" in fault.summary


def test_collection_check_is_skipped_for_a_replacement():
    """A replacement is PUT to an edit href, not posted to a collection."""
    metadata = _parse(entry_kwargs={"primary_category": "stat.AP"},
                      collection=None, replacing=True)
    assert metadata.primary_category == "stat.AP"


def test_alias_primary_is_canonicalized():
    """stat.TH is an alias for math.ST."""
    metadata = _parse(entry_kwargs={"primary_category": "stat.TH"},
                      collection="stat")
    assert metadata.primary_category == "math.ST"


# ----------------------------------------------------------- secondary categories


def test_secondary_categories_are_kept_primary_first():
    metadata = _parse(entry_kwargs={"categories": ["cs.AI", "cs.DL"]})
    assert metadata.categories == ["cs.CG", "cs.AI", "cs.DL"]
    assert metadata.secondary_categories == ["cs.AI", "cs.DL"]


def test_primary_repeated_as_a_category_is_not_duplicated():
    metadata = _parse(entry_kwargs={"categories": ["cs.CG", "cs.AI"]})
    assert metadata.categories == ["cs.CG", "cs.AI"]


def test_invalid_secondary_is_evcts():
    """03-cross.t:358-362 -- 'no such category: cond-mat'."""
    fault = _fault({"primary_category": "hep-ex", "categories": ["cond-mat"]},
                   collection="physics")
    assert fault.error.mnemonic == "EVCTS"
    assert "no such category: 'cond-mat'" in fault.summary


def test_more_than_five_categories_is_encts():
    """03-cross.t:153-157 -- primary plus four secondaries is the cap."""
    fault = _fault({"primary_category": "test.dis-nn",
                    "categories": ["test.mes-hall", "test.str-el", "test.soft",
                                   "test.stat-mech", "test.supr-con"]},
                   collection="test")
    assert fault.error.mnemonic == "ENCTS"
    assert "may not exceed 4 secondary categories" in fault.summary


def test_exactly_five_categories_is_accepted():
    metadata = _parse(entry_kwargs={
        "primary_category": "test.dis-nn",
        "categories": ["test.mes-hall", "test.str-el", "test.soft",
                       "test.stat-mech"]}, collection="test")
    assert len(metadata.categories) == 5


# ---------------------------------------------------------- cross-list rules


def test_gen_ph_may_not_be_a_cross():
    """03-cross.t:98-102, with the exact substring it matches."""
    fault = _fault({"primary_category": "test.dis-nn",
                    "categories": ["physics.gen-ph"]}, collection="test")
    assert "category element(s) invalid: cross to 'physics.gen-ph' not allowed" \
        in fault.summary


def test_gen_ph_is_allowed_as_the_primary():
    metadata = _parse(entry_kwargs={"primary_category": "physics.gen-ph"},
                      collection="physics")
    assert metadata.primary_category == "physics.gen-ph"


def test_general_primary_admits_no_crosses():
    """03-cross.t:253-257 and :306-310."""
    fault = _fault({"primary_category": "physics.gen-ph",
                    "categories": ["q-bio.OT", "q-bio.PE"]},
                   collection="physics")
    assert fault.error.mnemonic == "EGCCS"
    assert "Crosses are not permitted when the primary category is also a " \
        "general category" in fault.summary


def test_general_primary_cs_oh_admits_no_crosses():
    fault = _fault({"primary_category": "cs.OH",
                    "categories": ["cs.AI", "cs.DL"]}, collection="cs")
    assert fault.error.mnemonic == "EGCCS"


def test_general_cross_beside_another_category_of_its_archive():
    """03-cross.t:200-204 -- q-bio.OT is general, q-bio.PE shares its archive."""
    fault = _fault({"primary_category": "test.dis-nn",
                    "categories": ["q-bio.OT", "q-bio.PE"]},
                   collection="test")
    assert fault.error.mnemonic == "EGCTS"
    assert "Crosses to general categories are not permitted in addition to " \
        "other categories in the respective archives" in fault.summary


def test_general_cross_alone_is_allowed():
    metadata = _parse(entry_kwargs={"primary_category": "test.dis-nn",
                                    "categories": ["q-bio.OT"]},
                      collection="test")
    assert "q-bio.OT" in metadata.categories


# ------------------------------------------------------------------ replacement


def test_replacement_categories_must_match_the_existing_set():
    """ERCTS (AtomPP.pm:1036-1045)."""
    fault = _fault({"categories": ["cs.AI"]}, collection=None, replacing=True,
                   existing_categories=["cs.CG", "cs.DL"])
    assert fault.error.mnemonic == "ERCTS"


def test_replacement_with_a_matching_set_is_accepted():
    metadata = _parse(entry_kwargs={"categories": ["cs.AI"]}, collection=None,
                      replacing=True,
                      existing_categories=["cs.CG", "cs.AI"])
    assert set(metadata.categories) == {"cs.CG", "cs.AI"}


def test_replacement_with_no_categories_is_accepted():
    """"no category elements, or a set that matches" -- ERCTS message."""
    metadata = _parse(collection=None, replacing=True,
                      existing_categories=["cs.CG", "cs.AI"])
    assert metadata.categories == ["cs.CG"]


def test_replacement_skips_the_category_cap():
    metadata = _parse(entry_kwargs={
        "primary_category": "test.dis-nn",
        "categories": ["test.mes-hall", "test.str-el", "test.soft",
                       "test.stat-mech", "test.supr-con"]},
        collection=None, replacing=True, existing_categories=None)
    assert len(metadata.categories) == 6


# ---------------------------------------------------------------- ACM and MSC


def test_acm_classes_are_extracted():
    """AtomPP.pm:1008-1011."""
    document = wrapper_entry(**{**BASE, "categories": []}).replace(
        b"</entry>",
        b'  <category term="http://arxiv.org/terms/ACM1998/D.2.4"'
        b' scheme="http://arxiv.org/terms/ACM1998"/>\n</entry>')
    metadata = parse_wrapper(document, collection="cs", depositor="vtex",
                             deposit_extensions=lambda _: ["zip"],
                             deposit_owner=lambda _: "vtex")
    assert metadata.acm_class == "D.2.4"


def test_msc_classes_are_extracted():
    document = wrapper_entry(**{**BASE, "primary_category": "math.AC",
                                "categories": []}).replace(
        b"</entry>",
        b'  <category term="http://arxiv.org/terms/MSC2000/43A15"'
        b' scheme="http://arxiv.org/terms/MSC2000"/>\n</entry>')
    metadata = parse_wrapper(document, collection="math", depositor="vtex",
                             deposit_extensions=lambda _: ["zip"],
                             deposit_owner=lambda _: "vtex")
    assert metadata.msc_class == "43A15"


def test_no_acm_or_msc_by_default():
    metadata = _parse()
    assert metadata.acm_class is None
    assert metadata.msc_class is None


# --------------------------------------------------------------------- summary


def test_summary_of_exactly_twenty_characters_is_too_short():
    """AtomPP.pm:1088 uses ``> 20``, so 20 fails."""
    fault = _fault({"summary": "x" * 20})
    assert fault.error.mnemonic == "ENSUM"


def test_summary_of_twenty_one_characters_is_accepted():
    metadata = _parse(entry_kwargs={"summary": "x" * 21})
    assert len(metadata.summary) == 21


def test_categories_are_validated_before_the_summary():
    """Both wrong -> the category error, because that check runs first."""
    fault = _fault({"primary_category": "nope.NOPE", "summary": "short"})
    assert fault.error.mnemonic == "EVPCT"


# ----------------------------------------------------------------- media links


def test_media_ids_are_collected():
    metadata = _parse()
    assert metadata.media_ids == ["10030146"]


def test_multiple_media_links():
    metadata = _parse(
        entry_kwargs={"links": [
            MediaLink("https://arxiv.org/sword-app/edit/10030146", "application/zip"),
            MediaLink("https://arxiv.org/sword-app/edit/10030147", "application/pdf"),
        ]},
        deposit_extensions=lambda deposit_id:
            ["zip"] if deposit_id == "10030146" else ["pdf"])
    assert metadata.media_ids == ["10030146", "10030147"]


def test_http_hrefs_are_accepted():
    metadata = _parse(entry_kwargs={"links": [
        MediaLink("http://arxiv.org/sword-app/edit/10030146", "application/zip")]})
    assert metadata.media_ids == ["10030146"]


def test_no_related_links_is_enrel():
    fault = _fault({"links": []})
    assert fault.error.mnemonic == "ENREL"
    assert 'No media entries with link attribute rel="related"' in fault.summary


def test_unparseable_href_is_evlnk():
    fault = _fault({"links": [MediaLink("not a url", "application/zip")]})
    assert fault.error.mnemonic == "EVLNK"
    assert "Is the link href valid?" in fault.summary


def test_href_without_a_deposit_id_is_evlnk():
    fault = _fault({"links": [
        MediaLink("https://arxiv.org/sword-app/edit/abc", "application/zip")]})
    assert fault.error.mnemonic == "EVLNK"


def test_link_without_a_mime_subtype_is_elktp():
    fault = _fault({"links": [MediaLink(MEDIA_HREF, "application")]})
    assert fault.error.mnemonic == "ELKTP"


def test_unknown_deposit_is_enmdi():
    fault = _fault(deposit_extensions=lambda _: [])
    assert fault.error.mnemonic == "ENMDI"
    assert "info:arxiv/app/10030146" in fault.summary


def test_wrong_mime_type_reports_what_is_actually_there():
    """AtomPP.pm:1134-1138."""
    fault = _fault(deposit_extensions=lambda _: ["pdf"])
    assert fault.error.mnemonic == "ENMDI"
    assert "We have a media entry (10030146.pdf) instead" in fault.summary


def test_ambiguous_deposit_is_reported():
    """AtomPP.pm:1139-1142."""
    fault = _fault(deposit_extensions=lambda _: ["pdf", "ps"])
    assert fault.error.mnemonic == "ENMDI"
    assert "is ambiguous" in fault.summary


def test_referencing_another_depositors_media_is_refused():
    """Legacy only warned, with '## FIXME: this should be fatal'.

    Without this, a depositor can attach another user's staged files to their own
    submission.
    """
    fault = _fault(deposit_owner=lambda _: "someone-else")
    assert fault.error.mnemonic == "ENOWN"


def test_ownership_is_not_checked_when_no_depositor_is_given():
    metadata = _parse(depositor=None, deposit_owner=lambda _: "someone-else")
    assert metadata.media_ids == ["10030146"]


# --------------------------------------------------- arXiv extension elements


def test_extension_elements_are_extracted():
    """Never covered by the legacy suite -- its helper emitted them malformed."""
    metadata = _parse(entry_kwargs={
        "comments": ["24 pages, 2 figures"],
        "journal_refs": ["Nucl.Phys. B753 (2006) 295-312"],
        "dois": ["10.1016/j.nuclphysb.2006.07.013"],
        "report_nums": ["KUNS-2018"],
    })
    assert metadata.comments == "24 pages, 2 figures"
    assert metadata.journal_ref == "Nucl.Phys. B753 (2006) 295-312"
    assert metadata.doi == "10.1016/j.nuclphysb.2006.07.013"
    assert metadata.report_num == "KUNS-2018"


def test_repeated_extension_elements_are_joined_with_a_comma():
    """AtomPP.pm:1166."""
    metadata = _parse(entry_kwargs={"report_nums": ["KUNS-2018", "YITP-06-19"]})
    assert metadata.report_num == "KUNS-2018, YITP-06-19"


def test_absent_extension_elements_are_none():
    metadata = _parse()
    assert metadata.comments is None
    assert metadata.journal_ref is None
    assert metadata.doi is None
    assert metadata.report_num is None


# ------------------------------------------------------------------- malformed


def test_unparseable_xml_is_evxml():
    with pytest.raises(SwordFault) as excinfo:
        parse_wrapper(b"<entry><unclosed>")
    assert excinfo.value.error.mnemonic == "EVXML"
    assert "could not be parsed" in excinfo.value.summary


def test_wrong_root_element_is_evxml():
    with pytest.raises(SwordFault) as excinfo:
        parse_wrapper(b'<feed xmlns="http://www.w3.org/2005/Atom"/>')
    assert excinfo.value.error.mnemonic == "EVXML"


def test_missing_title_is_accepted():
    """ENTIT exists but AtomPP.pm:1183 never checks for a title."""
    metadata = _parse(entry_kwargs={"title": ""})
    assert metadata.title == ""


# ------------------------------------------------------------------- odds and ends


def test_links_that_are_not_related_are_ignored():
    """A real wrapper may carry alternate/self links; only related ones count."""
    document = wrapper_entry(**BASE).replace(
        b"</entry>",
        b'  <link rel="alternate" href="https://example.org/paper"/>\n</entry>')
    metadata = parse_wrapper(document, collection="cs", depositor="vtex",
                             deposit_extensions=lambda _: ["zip"],
                             deposit_owner=lambda _: "vtex")
    assert metadata.media_ids == ["10030146"]


def test_categories_that_canonicalize_together_are_deduplicated():
    """stat.TH and math.ST are the same category under two names."""
    metadata = _parse(entry_kwargs={"primary_category": "math.ST",
                                    "categories": ["stat.TH"]},
                      collection="math")
    assert metadata.categories.count("math.ST") >= 1
    # The cross-list rules see one category, not two.
    assert metadata.primary_category == "math.ST"


def test_group_of_an_unknown_category_is_none():
    from submit_ce.sword.atom.parse import group_of
    assert group_of("nope.NOPE") is None
    assert group_of("cs.CG") == "grp_cs"


def test_on_behalf_of_path_skips_nameless_contributors():
    metadata = _parse(entry_kwargs={"contributors": [
        Contributor("", email="nameless@example.org"),
        Contributor("Real Name")]},
        contact_override=("A. Scientist", "s@example.org"))
    assert metadata.authors == ["Real Name"]
