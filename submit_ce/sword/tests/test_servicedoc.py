"""The service document, rendered and served.

Reference: ``arxiv-lib/lib/arXiv/AtomPP/ServiceDoc.pm`` for the structure and
``submit_sword.md:210-299`` for the documented example. The end-to-end assertions
mirror ``arxiv-test-regression/pytest/tests/test_sword.py:57-71``, which is the
acceptance gate.
"""

from lxml import etree

from submit_ce.sword.atom import ns
from submit_ce.sword.atom.servicedoc import (
    APP,
    SERVICE_DOCUMENT_CONTENT_TYPE,
    max_upload_size_kb,
    render_service_document,
)
from submit_ce.sword.tests.client import basic_auth

SITE = "arxiv.org"


def _doc(group_ids=("grp_cs", "grp_stat"), **kwargs):
    kwargs.setdefault("site", SITE)
    return render_service_document(group_ids=list(group_ids), **kwargs)


def _tree(**kwargs):
    return etree.fromstring(_doc(**kwargs))


def _collections(root):
    return root.findall(f"{{{APP}}}workspace/{{{APP}}}collection")


# ---------------------------------------------------------------- document shape


def test_root_is_an_app_service_element():
    root = _tree()
    assert root.tag == f"{{{APP}}}service"


def test_sword_capability_elements():
    root = _tree()
    assert root.findtext(ns.qname(ns.SWORD, "version")) == "1.3"
    assert root.findtext(ns.qname(ns.SWORD, "verbose")) == "true"
    assert root.findtext(ns.qname(ns.SWORD, "noOp")) == "true"


def test_max_upload_size_reflects_the_real_50mb_limit():
    """Raised from legacy's 10000 kB per the plan's decision 5."""
    root = _tree()
    advertised = int(root.findtext(ns.qname(ns.SWORD, "maxUploadSize")))
    assert advertised == max_upload_size_kb()
    assert advertised == 51200  # 50 MiB in kB
    assert advertised > 10000


def test_workspace_is_titled_arxiv():
    root = _tree()
    assert root.findtext(f"{{{APP}}}workspace/{{{ns.ATOM}}}title") == "arXiv"


def test_no_https_namespaces():
    assert b'xmlns:sword="http://purl.org/net/sword/"' in _doc()
    assert b"https://purl.org" not in _doc()
    assert b"https://www.w3.org" not in _doc()


# ------------------------------------------------------------------ collections


def test_one_collection_per_permitted_group():
    root = _tree(group_ids=["grp_cs", "grp_stat", "grp_test"])
    assert len(_collections(root)) == 3


def test_no_collections_when_the_user_has_no_groups():
    """Legacy defaulted to every group instead (ServiceDoc.pm:104-107)."""
    root = _tree(group_ids=[])
    assert _collections(root) == []


def test_collection_href_shape():
    """submit_sword.md:229 and the regression suite's assertion."""
    root = _tree(group_ids=["grp_cs"])
    href = _collections(root)[0].get("href")
    assert href == "https://arxiv.org/sword-app/cs-collection"


def test_hyphenated_group_href():
    root = _tree(group_ids=["grp_q-bio"])
    assert _collections(root)[0].get("href") == \
        "https://arxiv.org/sword-app/q-bio-collection"


def test_collection_metadata():
    root = _tree(group_ids=["grp_stat"])
    collection = _collections(root)[0]
    assert collection.findtext(ns.qname(ns.ATOM, "title")) == \
        "The Statistics archive"
    assert collection.findtext(ns.qname(ns.SWORD, "collectionPolicy")) == \
        "Open Access"
    assert collection.findtext(ns.qname(ns.SWORD, "mediation")) == "true"
    assert collection.findtext(ns.qname(ns.SWORD, "treatment")) == \
        "will be posted pending moderator approval"
    assert collection.findtext(ns.qname(ns.DCTERMS, "abstract")) == \
        "The Statistics e-print archive at http://arxiv.org/"


def test_accepted_media_types():
    root = _tree(group_ids=["grp_cs"])
    accepted = [element.text
                for element in _collections(root)[0].iter(f"{{{APP}}}accept")]
    assert "application/zip" in accepted
    assert "application/atom+xml;type=entry" in accepted
    assert "application/pdf" in accepted
    assert len(accepted) == 11


def test_docx_is_still_advertised_though_deposits_of_it_are_rejected():
    """Legacy's mismatch (ServiceDoc.pm:78 vs AtomPP.pm:262-274), kept as-is."""
    root = _tree(group_ids=["grp_cs"])
    accepted = [element.text
                for element in _collections(root)[0].iter(f"{{{APP}}}accept")]
    assert any("wordprocessingml" in value for value in accepted)


def test_accept_packaging_offers_zip_only():
    """The Data Conservancy packaging is dead and now answers 415."""
    root = _tree(group_ids=["grp_cs"])
    packaging = [element.text for element
                 in _collections(root)[0].iter(ns.qname(ns.SWORD, "acceptPackaging"))]
    assert packaging == ["http://purl.org/net/sword-types/bagit"]
    assert not any("dataconservancy" in value for value in packaging)


# ------------------------------------------------------------------- categories


def test_primary_categories_are_wrapped_and_fixed():
    """submit_sword.md:277 -- <arxiv:primary_categories fixed="yes">."""
    root = _tree(group_ids=["grp_stat"])
    wrapper = _collections(root)[0].find(ns.qname(ns.ARXIV, "primary_categories"))
    assert wrapper is not None
    assert wrapper.get("fixed") == "yes"
    terms = [element.get("term")
             for element in wrapper.iter(ns.qname(ns.ARXIV, "primary_category"))]
    assert "http://arxiv.org/terms/arXiv/stat.AP" in terms


def test_primary_category_attributes_match_the_manual():
    root = _tree(group_ids=["grp_stat"])
    wrapper = _collections(root)[0].find(ns.qname(ns.ARXIV, "primary_categories"))
    element = next(e for e in wrapper.iter(ns.qname(ns.ARXIV, "primary_category"))
                   if e.get("term").endswith("stat.AP"))
    assert element.get("scheme") == "http://arxiv.org/terms/arXiv/"
    assert element.get("label") == "Statistics - Applications"


def test_secondary_categories_are_atom_category_elements():
    root = _tree(group_ids=["grp_stat"])
    categories = _collections(root)[0].find(f"{{{APP}}}categories")
    assert categories.get("fixed") == "yes"
    terms = [element.get("term")
             for element in categories.iter(ns.qname(ns.ATOM, "category"))]
    assert "http://arxiv.org/terms/arXiv/stat.AP" in terms


def test_each_collection_lists_only_its_own_categories():
    """The ServiceDoc.pm:147-151 bug is not reproduced (decision 1)."""
    root = _tree(group_ids=["grp_cs", "grp_stat"])
    cs, stat = _collections(root)

    def terms(collection):
        wrapper = collection.find(ns.qname(ns.ARXIV, "primary_categories"))
        return {e.get("term")
                for e in wrapper.iter(ns.qname(ns.ARXIV, "primary_category"))}

    assert "http://arxiv.org/terms/arXiv/cs.CG" in terms(cs)
    assert "http://arxiv.org/terms/arXiv/cs.CG" not in terms(stat)
    assert "http://arxiv.org/terms/arXiv/stat.AP" in terms(stat)
    assert "http://arxiv.org/terms/arXiv/stat.AP" not in terms(cs)


# ------------------------------------------------------------- the served route


def test_servicedocument_requires_credentials(client):
    response = client.get("/sword-app/servicedocument")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Basic realm="SWORD at arXiv"'
    assert response.headers["content-type"].startswith("application/xml")
    assert b"<arxiv:errorcode>33554432</arxiv:errorcode>" in response.content


def test_servicedocument_rejects_a_bad_password(client, depositor):
    response = client.get(
        "/sword-app/servicedocument",
        headers={"Authorization": basic_auth(depositor.nickname, "wrong")})
    assert response.status_code == 401
    assert b"<arxiv:errorcode>33554432</arxiv:errorcode>" in response.content


def test_servicedocument_rejects_an_unprivileged_user(client, plain_user):
    response = client.get(
        "/sword-app/servicedocument",
        headers={"Authorization": basic_auth(plain_user.nickname,
                                            plain_user.password)})
    assert response.status_code == 401
    assert b"special privileges" in response.content


def test_servicedocument_requires_a_license(client, unlicensed_depositor):
    response = client.get(
        "/sword-app/servicedocument",
        headers={"Authorization": basic_auth(unlicensed_depositor.nickname,
                                            unlicensed_depositor.password)})
    assert response.status_code == 412
    assert b"<arxiv:errorcode>268435456</arxiv:errorcode>" in response.content
    assert b"sword-license" in response.content


def test_servicedocument_is_served_to_a_valid_depositor(client, depositor):
    response = client.get(
        "/sword-app/servicedocument",
        headers={"Authorization": basic_auth(depositor.nickname,
                                            depositor.password)})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(SERVICE_DOCUMENT_CONTENT_TYPE)

    root = etree.fromstring(response.content)
    hrefs = {collection.get("href") for collection in _collections(root)}
    assert hrefs == {
        "https://arxiv.org/sword-app/physics-collection",
        "https://arxiv.org/sword-app/cs-collection",
        "https://arxiv.org/sword-app/test-collection",
    }


def test_served_document_satisfies_the_live_regression_assertions(client, depositor):
    """The exact strings arxiv-test-regression/tests/test_sword.py:65-68 checks."""
    response = client.get(
        "/sword-app/servicedocument",
        headers={"Authorization": basic_auth(depositor.nickname,
                                            depositor.password)})
    body = response.text

    assert "arxiv.org/sword-app/test-collection" in body
    assert "arxiv.org/sword-app/cs-collection" in body
    assert "http://arxiv.org/terms/arXiv/test.dis-nn" in body
    assert "http://arxiv.org/terms/arXiv/cs.CG" in body
    assert "<summary>Not Authorized: SWORD deposit requires" not in body


def test_servicedocument_honours_on_behalf_of(client, depositor, sword_db):
    """The mediated user's privileges shape the response (AtomPP.pm:356-361)."""
    import arxiv.db.models as models
    from arxiv.db import Session

    # A second account permitted only for maths.
    Session.add(models.TapirUser(
        user_id=77777, email="mathsonly@example.org",
        first_name="Maths", last_name="Only", policy_class=2,
        flag_email_verified=1, flag_approved=1,
        demographics=models.Demographic(
            country="us", affiliation="X", type=3, url="", archive="",
            subject_class="", original_subject_classes="",
            flag_xml=1, flag_proxy=1, veto_status="ok",
            flag_group_math=1),
        tapir_nicknames=models.TapirNickname(
            nickname="mathsonly", flag_valid=1, flag_primary=1)))
    Session.commit()

    response = client.get(
        "/sword-app/servicedocument",
        headers={"Authorization": basic_auth(depositor.nickname,
                                             depositor.password),
                 "X-On-Behalf-Of": "mathsonly"})
    assert response.status_code == 200
    root = etree.fromstring(response.content)
    hrefs = {collection.get("href") for collection in _collections(root)}
    assert hrefs == {"https://arxiv.org/sword-app/math-collection"}


def test_unsupported_method_is_405_with_a_plain_body(client):
    """AtomPP.pm:147-153 answers the bare string 'unsupported'."""
    response = client.request("PATCH", "/sword-app/servicedocument")
    assert response.status_code == 405
    assert response.text == "unsupported"


def test_status_still_works(client):
    assert client.get("/status").text == "ok"
