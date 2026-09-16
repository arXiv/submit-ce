"""The remaining protocol verbs: entry retrieval, and the refusals.

``AtomPP.pm:352-411`` for GET dispatch and ``:539-546`` for DELETE. Every path that
is not a recognised request has its own error code, and clients rely on them to tell
a misconfiguration from a rejection.
"""

from lxml import etree

from submit_ce.sword.tests import client as sword_client
from submit_ce.sword.tests.client import basic_auth

ZIP = b"PK\x03\x04 pretend this is a zip"


def _auth(depositor):
    return {"Authorization": basic_auth(depositor.nickname, depositor.password)}


def _deposit(client, depositor, collection="cs"):
    response = client.post(
        f"/sword-app/{collection}-collection", content=ZIP,
        headers={**_auth(depositor), "Content-Type": "application/zip"})
    assert response.status_code == 201, response.text
    return str(sword_client.sword_id(response.content)), response.content


# ------------------------------------------------------------ entry retrieval


def test_getid_serves_the_stored_entry(client, depositor):
    """``AtomPP.pm:367-383`` re-serves the ``.atom`` written at deposit time."""
    deposit_id, original = _deposit(client, depositor)
    response = client.get(f"/sword-app/getid/app/{deposit_id}",
                          headers=_auth(depositor))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/atom+xml;type=entry")
    assert response.content == original


def test_edit_atom_serves_the_same_entry(client, depositor):
    """The ``rel="edit"`` href from the deposit response."""
    deposit_id, original = _deposit(client, depositor)
    response = client.get(f"/sword-app/edit/{deposit_id}.atom",
                          headers=_auth(depositor))
    assert response.status_code == 200
    assert response.content == original


def test_edit_href_from_the_response_resolves(client, depositor):
    """Follow the link the server itself handed out."""
    _, entry = _deposit(client, depositor)
    href = sword_client.edit_link(entry)
    path = href.replace("https://arxiv.org", "")

    response = client.get(path, headers=_auth(depositor))
    assert response.status_code == 200
    assert etree.fromstring(response.content).tag.endswith("entry")


def test_retrieval_is_cacheable(client, depositor):
    """Legacy sets a one-day expiry (``AtomPP.pm:382``)."""
    deposit_id, _ = _deposit(client, depositor)
    response = client.get(f"/sword-app/getid/app/{deposit_id}",
                          headers=_auth(depositor))
    assert response.headers["Cache-Control"] == "max-age=86400"


def test_unknown_deposit_is_enmdi(client, depositor):
    response = client.get("/sword-app/getid/app/10039999",
                          headers=_auth(depositor))
    assert response.status_code == 400
    assert b"<arxiv:errorcode>524288</arxiv:errorcode>" in response.content
    assert b"info:arxiv/app/10039999" in response.content


def test_another_depositors_entry_is_enown(client, depositor,
                                          unlicensed_depositor):
    """``AtomPP.pm:384-388``. Ownership is recorded on the deposit."""
    deposit_id, _ = _deposit(client, depositor)

    # unlicensed_depositor cannot get past the license gate, so grant one.
    import arxiv.db.models as models
    from datetime import datetime, timezone
    from arxiv.db import Session
    Session.add(models.SwordLicense(
        user_id=unlicensed_depositor.user_id,
        license="http://arxiv.org/licenses/nonexclusive-distrib/1.0/",
        updated=datetime.now(timezone.utc)))
    Session.commit()

    response = client.get(f"/sword-app/getid/app/{deposit_id}",
                          headers=_auth(unlicensed_depositor))
    assert response.status_code == 400
    assert b"<arxiv:errorcode>134217728</arxiv:errorcode>" in response.content


def test_retrieval_requires_credentials(client, depositor):
    deposit_id, _ = _deposit(client, depositor)
    response = client.get(f"/sword-app/getid/app/{deposit_id}")
    assert response.status_code == 401


# ---------------------------------------------------------------- GET refusals


def test_get_on_a_non_atom_edit_path_is_eblog(client, depositor):
    """``AtomPP.pm:395-399`` -- an /edit GET only works on the rel="edit" href."""
    deposit_id, _ = _deposit(client, depositor)
    response = client.get(f"/sword-app/edit/{deposit_id}",
                          headers=_auth(depositor))
    assert response.status_code == 400
    assert b"<arxiv:errorcode>67108864</arxiv:errorcode>" in response.content


def test_get_on_a_collection_is_egtpt(client):
    """``AtomPP.pm:400-404`` -- collections are POST-only."""
    response = client.get("/sword-app/cs-collection")
    assert response.status_code == 400
    assert b"<arxiv:errorcode>8</arxiv:errorcode>" in response.content
    assert b"Use POST instead" in response.content
    assert b"SWORD APP profile 1.0 and 1.1" in response.content


def test_unrecognized_get_is_evgrq(client):
    """``AtomPP.pm:405-410``."""
    response = client.get("/sword-app/nonsense")
    assert response.status_code == 400
    assert b"<arxiv:errorcode>4</arxiv:errorcode>" in response.content


def test_servicedocument_is_not_swallowed_by_the_catch_all(client, depositor):
    """Route order matters: the specific path must win."""
    response = client.get("/sword-app/servicedocument", headers=_auth(depositor))
    assert response.status_code == 200
    assert b"<sword:version>1.3</sword:version>" in response.content


# --------------------------------------------------------------------- DELETE


def test_delete_is_not_implemented(client, depositor):
    """``AtomPP.pm:539-546`` -- there are no valid DELETE actions."""
    response = client.delete("/sword-app/edit/10030146",
                             headers=_auth(depositor))
    assert response.status_code == 501
    assert b"<arxiv:errorcode>1</arxiv:errorcode>" in response.content
    assert b"method not supported" in response.content


def test_delete_on_a_collection_is_also_refused(client):
    assert client.delete("/sword-app/cs-collection").status_code == 501


# ------------------------------------------------------------------------ PUT


def test_put_outside_edit_is_not_implemented(client, depositor):
    """``AtomPP.pm:416-422``."""
    response = client.put("/sword-app/cs-collection", content=b"<entry/>",
                          headers=_auth(depositor))
    assert response.status_code == 501
    assert b"<arxiv:errorcode>1</arxiv:errorcode>" in response.content


# --------------------------------------------------------- unsupported methods


def test_patch_is_405_with_a_plain_body(client):
    """``AtomPP.pm:147-153`` answers the bare string 'unsupported'."""
    response = client.request("PATCH", "/sword-app/cs-collection")
    assert response.status_code == 405
    assert response.text == "unsupported"


def test_head_is_405(client):
    """HEAD is not in the whitelist either."""
    assert client.request("HEAD", "/sword-app/servicedocument").status_code == 405
