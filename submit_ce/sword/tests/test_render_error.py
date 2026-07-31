"""The ``<sword:error>`` document must match the legacy shape.

Reference: ``arxiv-lib/lib/arXiv/AtomPP/Error.pm:44-121`` for the structure, and
``arxiv-docs/source/help/submit_sword.md:398-417,855-875`` for worked examples --
with the caveat that the manual's namespace URIs are rendered ``https``, which is
a docs artifact. The code emits ``http``; see `submit_ce.sword.atom.ns`.
"""

from datetime import datetime, timezone

from lxml import etree

from submit_ce.sword.atom import ns
from submit_ce.sword.atom.render import ERROR_CONTENT_TYPE, iso_z, render_error
from submit_ce.sword.errors import SwordFault

MOMENT = datetime(2008, 4, 29, 19, 38, 5, tzinfo=timezone.utc)
FIXED_ID = "79652319-FB86-3C12-AC51-46D44EF5A410"


def _render(fault, **kwargs):
    kwargs.setdefault("site", "arxiv.org")
    kwargs.setdefault("timestamp", MOMENT)
    kwargs.setdefault("entry_id", FIXED_ID)
    return render_error(fault, **kwargs)


def _tree(fault, **kwargs):
    return etree.fromstring(_render(fault, **kwargs))


def test_root_is_sword_error_with_the_href_for_the_code():
    root = _tree(SwordFault("EVMD5"))
    assert root.tag == ns.qname(ns.SWORD, "error")
    assert root.get("href") == \
        "http://purl.org/net/sword/error/ErrorChecksumMismatch"


def test_namespaces_are_declared_with_atom_as_the_default():
    root = _tree(SwordFault("EVMD5"))
    assert root.nsmap[None] == "http://www.w3.org/2005/Atom"
    assert root.nsmap["sword"] == "http://purl.org/net/sword/"
    assert root.nsmap["arxiv"] == "http://arxiv.org/schemas/atom/"


def test_no_https_namespace_anywhere():
    """The manual shows https; clients match the http form."""
    assert b"https://" not in _render(SwordFault("EVMD5"))


def test_element_order_matches_error_pm():
    root = _tree(SwordFault("EVCOL", "foobar"))
    tags = [etree.QName(child).localname for child in root]
    assert tags == ["author", "title", "id", "updated", "source",
                    "treatment", "link", "errorcode", "summary"]


def test_author_title_and_treatment_are_the_fixed_legacy_values():
    root = _tree(SwordFault("EVCOL"))
    assert root.findtext(f"{{{ns.ATOM}}}author/{{{ns.ATOM}}}name") == "SWORD@arXiv"
    assert root.findtext(f"{{{ns.ATOM}}}title") == "ERROR"
    assert root.findtext(f"{{{ns.SWORD}}}treatment") == "processing failed"


def test_id_is_an_info_arxiv_uri():
    root = _tree(SwordFault("EVCOL"))
    assert root.findtext(f"{{{ns.ATOM}}}id") == f"info:arxiv/{FIXED_ID}"


def test_id_varies_between_errors_when_not_injected():
    """Deliberate deviation: the Perl emits one constant id for every error."""
    first = render_error(SwordFault("EVCOL"), site="arxiv.org")
    second = render_error(SwordFault("EVCOL"), site="arxiv.org")
    assert _id_of(first) != _id_of(second)


def _id_of(document: bytes) -> str:
    return etree.fromstring(document).findtext(f"{{{ns.ATOM}}}id")


def test_updated_is_second_precision_utc():
    root = _tree(SwordFault("EVCOL"))
    assert root.findtext(f"{{{ns.ATOM}}}updated") == "2008-04-29T19:38:05Z"


def test_generator_carries_uri_and_version():
    root = _tree(SwordFault("EVCOL"), site="export.arxiv.org")
    generator = root.find(f"{{{ns.ATOM}}}source/{{{ns.ATOM}}}generator")
    assert generator.text == "SWORD@arXiv.org"
    assert generator.get("uri") == "http://export.arxiv.org/sword-app/"
    assert generator.get("version") == "1.1"


def test_alternate_link_points_at_main_site_help():
    root = _tree(SwordFault("EVCOL"), site="export.arxiv.org",
                 main_site="arxiv.org")
    link = root.find(f"{{{ns.ATOM}}}link")
    assert link.get("rel") == "alternate"
    assert link.get("href") == "http://arxiv.org/help"
    assert link.get("type") == "text/html"


def test_main_site_defaults_to_site():
    root = _tree(SwordFault("EVCOL"), site="export.arxiv.org")
    assert root.find(f"{{{ns.ATOM}}}link").get("href") == \
        "http://export.arxiv.org/help"


def test_errorcode_and_summary():
    root = _tree(SwordFault("EVCOL", "foobar"))
    assert root.findtext(f"{{{ns.ARXIV}}}errorcode") == "16"
    assert root.findtext(f"{{{ns.ATOM}}}summary") == "invalid collection: foobar"


def test_checksum_mismatch_matches_the_manual_example():
    """submit_sword.md:398-417: code 1048576, 'MD5 sum did not match'."""
    root = _tree(SwordFault("EVMD5"))
    assert root.findtext(f"{{{ns.ARXIV}}}errorcode") == "1048576"
    assert root.findtext(f"{{{ns.ATOM}}}summary") == "MD5 sum did not match"


def test_document_has_an_xml_declaration():
    assert _render(SwordFault("EVCOL")).startswith(b"<?xml")


def test_error_content_type_is_application_xml():
    """Not application/atom+xml, even though the body is an Atom entry."""
    assert ERROR_CONTENT_TYPE == "application/xml"


def test_iso_z_converts_to_utc():
    from datetime import timedelta
    eastern = timezone(timedelta(hours=-5))
    assert iso_z(datetime(2008, 4, 29, 14, 38, 5, tzinfo=eastern)) == \
        "2008-04-29T19:38:05Z"


def test_iso_z_drops_microseconds():
    assert iso_z(datetime(2008, 4, 29, 19, 38, 5, 123456,
                          tzinfo=timezone.utc)) == "2008-04-29T19:38:05Z"
