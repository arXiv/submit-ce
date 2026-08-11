"""Media deposit: ``POST /sword-app/<collection>-collection`` -> 201.

This is the first half of ``02-deposit.t`` and of the live regression suite's
``test_paper_upload`` (``arxiv-test-regression/pytest/tests/test_sword.py:87-118``),
now runnable in-process against mock stores rather than only against a deployed
service.
"""

import base64
import hashlib

from lxml import etree

from submit_ce.sword.atom import ns
from submit_ce.sword.tests import client as sword_client
from submit_ce.sword.deposits import max_deposit_bytes
from submit_ce.sword.tests.client import ATOM_ENTRY_TYPE, basic_auth, content_md5

ZIP = b"PK\x03\x04 pretend this is a zip"
PDF = b"%PDF-1.4\n%%EOF\n"


def _auth(depositor):
    return basic_auth(depositor.nickname, depositor.password)


def _post(client, depositor, collection="cs", payload=ZIP,
          content_type="application/zip", **headers):
    request_headers = {"Authorization": _auth(depositor),
                       "Content-Type": content_type}
    request_headers.update(headers)
    return client.post(f"/sword-app/{collection}-collection",
                       content=payload, headers=request_headers)


# ------------------------------------------------------------------ happy path


def test_media_deposit_is_created(client, depositor):
    response = _post(client, depositor)
    assert response.status_code == 201


def test_response_is_an_atom_entry(client, depositor):
    response = _post(client, depositor)
    assert response.headers["content-type"].startswith(
        "application/atom+xml;type=entry")
    root = etree.fromstring(response.content)
    assert root.tag == ns.qname(ns.ATOM, "entry")


def test_location_points_at_getid(client, depositor):
    """submit_sword.md:354-357."""
    response = _post(client, depositor)
    location = response.headers["Location"]
    assert location.startswith("https://arxiv.org/sword-app/getid/app/")


def test_entry_id_and_links(client, depositor):
    response = _post(client, depositor)
    deposit_id = sword_client.sword_id(response.content)
    assert deposit_id is not None

    assert sword_client.entry_id(response.content) == f"info:arxiv/app/{deposit_id}"
    assert sword_client.edit_media_link(response.content) == \
        f"https://arxiv.org/sword-app/edit/{deposit_id}"
    assert sword_client.edit_link(response.content) == \
        f"https://arxiv.org/sword-app/edit/{deposit_id}.atom"


def test_media_response_has_no_alternate_link(client, depositor):
    """Nothing to track until a wrapper initiates ingestion."""
    response = _post(client, depositor)
    assert sword_client.alternate_link(response.content) is None


def test_entry_reports_the_depositor_and_treatment(client, depositor):
    response = _post(client, depositor)
    root = etree.fromstring(response.content)
    assert root.findtext(f"{{{ns.ATOM}}}author/{{{ns.ATOM}}}name") == \
        depositor.nickname
    assert root.findtext(ns.qname(ns.SWORD, "treatment")) == \
        "stored in author's workspace"
    assert root.findtext(ns.qname(ns.ATOM, "title")) == \
        "Accepted media deposit to arXiv"


def test_summary_names_the_media_type(client, depositor):
    response = _post(client, depositor)
    root = etree.fromstring(response.content)
    assert root.findtext(ns.qname(ns.ATOM, "summary")) == \
        ('A media deposit of type "application/zip" was stored in the '
         "author's workspace")


def test_primary_category_names_the_collection_not_a_category(client, depositor):
    """The subject category is not known yet (submit_sword.md:386)."""
    response = _post(client, depositor, collection="cs")
    root = etree.fromstring(response.content)
    primary = root.find(ns.qname(ns.ARXIV, "primary_category"))
    assert primary.get("term") == "http://arxiv.org/terms/arXiv/cs"
    assert primary.text == "Computer Science"


def test_content_element_points_at_the_edit_media_url(client, depositor):
    response = _post(client, depositor, content_type="application/pdf",
                     payload=PDF)
    root = etree.fromstring(response.content)
    content = root.find(ns.qname(ns.ATOM, "content"))
    assert content.get("type") == "application/pdf"
    assert content.get("src").endswith(
        str(sword_client.sword_id(response.content)))


def test_bytes_are_stored_and_owned(client, depositor, sword_app):
    response = _post(client, depositor)
    deposit_id = str(sword_client.sword_id(response.content))
    store = sword_app.state.deposits

    assert store.read(deposit_id) == ZIP
    assert store.owned_by(deposit_id, depositor.nickname)
    assert not store.owned_by(deposit_id, "someone-else")


def test_response_entry_is_kept_for_later_retrieval(client, depositor, sword_app):
    """Legacy writes <id>.atom so GET can re-serve it (AtomPP.pm:325-335)."""
    response = _post(client, depositor)
    deposit_id = str(sword_client.sword_id(response.content))
    assert sword_app.state.deposits.read_entry(deposit_id) == response.content


def test_successive_deposits_get_distinct_ids(client, depositor):
    first = sword_client.sword_id(_post(client, depositor).content)
    second = sword_client.sword_id(_post(client, depositor).content)
    assert first != second


# ------------------------------------------------------------------ media types


def test_pdf_deposit(client, depositor):
    response = _post(client, depositor, payload=PDF,
                     content_type="application/pdf")
    assert response.status_code == 201


def test_unsupported_media_type_is_415(client, depositor):
    response = _post(client, depositor, content_type="text/plain",
                     payload=b"hello")
    assert response.status_code == 415
    assert b"<arxiv:errorcode>131072</arxiv:errorcode>" in response.content


def test_docx_is_refused_though_advertised(client, depositor):
    docx = ("application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document")
    assert _post(client, depositor, content_type=docx).status_code == 415


# ---------------------------------------------------------------------- Content-MD5


def test_matching_checksum_is_accepted(client, depositor):
    response = _post(client, depositor, **{"Content-MD5": content_md5(ZIP)})
    assert response.status_code == 201


def test_hex_checksum_is_accepted(client, depositor):
    digest = hashlib.md5(ZIP).hexdigest()
    response = _post(client, depositor, **{"Content-MD5": digest})
    assert response.status_code == 201


def test_mismatched_checksum_is_412(client, depositor):
    """submit_sword.md:388-417."""
    wrong = base64.b64encode(hashlib.md5(b"other").digest()).decode()
    response = _post(client, depositor, **{"Content-MD5": wrong})
    assert response.status_code == 412
    assert b"<arxiv:errorcode>1048576</arxiv:errorcode>" in response.content
    assert b"MD5 sum did not match" in response.content


def test_a_failed_checksum_stores_nothing(client, depositor, sword_app):
    wrong = base64.b64encode(hashlib.md5(b"other").digest()).decode()
    _post(client, depositor, **{"Content-MD5": wrong})
    assert sword_app.state.deposits.deposits == {}


# ------------------------------------------------------------------- collections


def test_deposit_to_an_unpermitted_collection_is_refused(client, depositor):
    """The fixture depositor holds physics, cs and test -- not math."""
    response = _post(client, depositor, collection="math")
    assert response.status_code == 401
    assert b"<arxiv:errorcode>33554432</arxiv:errorcode>" in response.content
    assert b"posting to &#39;math&#39;" in response.content or \
        b"posting to 'math'" in response.content


def test_unknown_collection_is_evcol(client, depositor):
    """submit_sword.md:845-875 documents EVCOL with 'invalid collection'.

    Legacy could not actually produce this -- its substring permission check ran
    first and answered EAUTH -- so this is the documented behaviour rather than
    the observed one.
    """
    response = _post(client, depositor, collection="foobar")
    assert response.status_code == 400
    assert b"<arxiv:errorcode>16</arxiv:errorcode>" in response.content
    assert b"invalid collection: foobar" in response.content


def test_deposit_requires_credentials(client):
    response = client.post("/sword-app/cs-collection", content=ZIP,
                           headers={"Content-Type": "application/zip"})
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Basic realm="SWORD at arXiv"'


def test_deposit_requires_privileges(client, plain_user):
    response = _post(client, plain_user)
    assert response.status_code == 401
    assert b"special privileges" in response.content


def test_deposit_requires_a_license(client, unlicensed_depositor):
    response = _post(client, unlicensed_depositor)
    assert response.status_code == 412
    assert b"<arxiv:errorcode>268435456</arxiv:errorcode>" in response.content


# ---------------------------------------------------------------- X-On-Behalf-Of


def test_mediated_deposit_records_the_contact_author(client, depositor):
    response = _post(client, depositor, **{
        "X-On-Behalf-Of": '"A. Scientist" <ascientist@example.org>'})
    assert response.status_code == 201

    root = etree.fromstring(response.content)
    contributor = root.find(ns.qname(ns.ATOM, "contributor"))
    assert contributor.findtext(ns.qname(ns.ATOM, "name")) == "A. Scientist"
    assert contributor.findtext(ns.qname(ns.ATOM, "email")) == \
        "ascientist@example.org"


def test_malformed_on_behalf_of_is_evcml(client, depositor):
    response = _post(client, depositor, **{"X-On-Behalf-Of": "not an email"})
    assert response.status_code == 400
    assert b"<arxiv:errorcode>512</arxiv:errorcode>" in response.content


def test_suspect_on_behalf_of_is_refused_at_the_media_step(client, depositor,
                                                           suspect_author):
    """04-suspect.t:104-120 -- the refusal happens on the *media* deposit.

    ``process_sword_headers`` runs on media POSTs too (``AtomPP.pm:885-890``), so
    a flagged contact author never gets as far as the wrapper.
    """
    response = _post(client, depositor, **{
        "X-On-Behalf-Of": f"<{suspect_author.email}>"})
    assert response.status_code == 400
    assert b"<arxiv:errorcode>512</arxiv:errorcode>" in response.content
    assert b"must submit directly" in response.content


# --------------------------------------------------------------------- X-No-Op


def test_no_op_deposit_answers_200_without_a_location(client, depositor):
    response = _post(client, depositor, **{"X-No-Op": "True"})
    assert response.status_code == 200
    assert "Location" not in response.headers
    root = etree.fromstring(response.content)
    assert root.findtext(ns.qname(ns.SWORD, "noOp")) == "true"


def test_no_op_false_behaves_as_a_real_deposit(client, depositor):
    response = _post(client, depositor, **{"X-No-Op": "false"})
    assert response.status_code == 201
    root = etree.fromstring(response.content)
    assert root.findtext(ns.qname(ns.SWORD, "noOp")) == "false"


# -------------------------------------------------------- other SWORD headers


def test_verbose_adds_a_verbose_description(client, depositor):
    response = _post(client, depositor, **{"X-Verbose": "True"})
    root = etree.fromstring(response.content)
    assert root.findtext(ns.qname(ns.SWORD, "verboseDescription")) == \
        "stored as is"


def test_verbose_description_absent_by_default(client, depositor):
    root = etree.fromstring(_post(client, depositor).content)
    assert root.find(ns.qname(ns.SWORD, "verboseDescription")) is None


def test_user_agent_is_echoed(client, depositor):
    response = _post(client, depositor,
                     **{"User-Agent": "arXiv SWORD demo 1.1"})
    root = etree.fromstring(response.content)
    assert root.findtext(ns.qname(ns.SWORD, "userAgent")) == \
        "arXiv SWORD demo 1.1"


def test_packaging_is_echoed(client, depositor):
    bagit = "http://purl.org/net/sword-types/bagit"
    response = _post(client, depositor, **{"X-Packaging": bagit})
    root = etree.fromstring(response.content)
    assert root.findtext(ns.qname(ns.SWORD, "packaging")) == bagit


def test_rejected_packaging_is_415(client, depositor):
    response = _post(client, depositor, **{
        "X-Packaging": "http://datapub.dataconservancy.org/package"})
    assert response.status_code == 415


def test_content_disposition_filename_is_echoed(client, depositor):
    """Legacy parses the filename and echoes it back (AtomPP.pm:320-323)."""
    response = _post(client, depositor, **{
        "Content-Disposition": "attachment; filename=paper.zip"})
    assert response.status_code == 201
    assert response.headers["Content-Disposition"] == "paper.zip"


def test_no_content_disposition_when_none_was_sent(client, depositor):
    response = _post(client, depositor)
    assert "Content-Disposition" not in response.headers


# --------------------------------------------------------- wrapper vs media split


def test_an_atom_content_type_is_routed_to_the_wrapper_path(client, depositor):
    """The same URL serves both; Content-Type decides (AtomPP.pm:262-274).

    An empty entry reaches the wrapper validator and is refused there for having no
    contact email, rather than being stored as media. Wrapper behaviour proper is
    covered in test_wrapper_deposit.py.
    """
    response = _post(client, depositor,
                     content_type="application/atom+xml;type=entry",
                     payload=b'<entry xmlns="http://www.w3.org/2005/Atom"/>')
    assert response.status_code == 400
    assert b"<arxiv:errorcode>256</arxiv:errorcode>" in response.content


def test_an_atom_wrapper_is_not_stored_as_media(client, depositor, sword_app):
    _post(client, depositor, content_type="application/atom+xml;type=entry",
          payload=b'<entry xmlns="http://www.w3.org/2005/Atom"/>')
    assert sword_app.state.deposits.deposits == {}


# ------------------------------------------------------------------ size limit

def _oversize() -> bytes:
    return b"x" * (max_deposit_bytes() + 1)


def _errorcode(response) -> str:
    return etree.fromstring(response.content).findtext(
        ns.qname(ns.ARXIV, "errorcode"))


ESIZE_CODE = "34359738368"


def test_oversize_media_deposit_is_413(client, depositor):
    response = _post(client, depositor, payload=_oversize())
    assert response.status_code == 413
    assert _errorcode(response) == ESIZE_CODE
    assert b"exceeds the" in response.content


def test_oversize_wrapper_deposit_is_413(client, depositor):
    """The gap finding 4 was about.

    ``check_size`` used to be reached only through ``store.save()``, i.e. the media
    path, so an Atom wrapper was parsed into a DOM at any size. Legacy capped the
    whole request regardless of content type (``$CGI::POST_MAX``, ``AtomPP.pm:9``),
    so this was a regression rather than merely a missing guard.
    """
    padding = "z" * max_deposit_bytes()
    document = ('<?xml version="1.0"?><entry xmlns="http://www.w3.org/2005/Atom">'
                f"<title>{padding}</title></entry>").encode()

    response = _post(client, depositor, payload=document,
                     content_type=ATOM_ENTRY_TYPE)
    assert response.status_code == 413
    assert _errorcode(response) == ESIZE_CODE


def test_both_paths_report_the_same_error(client, depositor):
    """One limit, one code, whichever content type carried the body."""
    media = _post(client, depositor, payload=_oversize())
    wrapper = _post(client, depositor, payload=_oversize(),
                    content_type=ATOM_ENTRY_TYPE)

    assert media.status_code == wrapper.status_code == 413
    assert _errorcode(media) == _errorcode(wrapper) == ESIZE_CODE


def test_a_deposit_at_exactly_the_limit_is_still_accepted(client, depositor):
    """Off-by-one: the limit is inclusive."""
    response = _post(client, depositor, payload=b"x" * max_deposit_bytes())
    assert response.status_code == 201


def test_size_is_checked_before_the_checksum(client, depositor):
    """An oversize body should not be hashed first, and reports ESIZE not EVMD5.

    Both would be legitimate refusals; the size answer is the useful one, and it
    avoids an MD5 over 50 MiB that the deposit is going to lose anyway.
    """
    response = _post(client, depositor, payload=_oversize(),
                     **{"Content-MD5": "obviously-not-the-right-digest"})
    assert response.status_code == 413
    assert _errorcode(response) == ESIZE_CODE
