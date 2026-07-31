"""Wrapper deposit: ``POST`` an Atom entry -> 202 and a real submission.

The second half of ``02-deposit.t`` and of the live suite's
``test_metadata_upload`` (``arxiv-test-regression/pytest/tests/test_sword.py:123-192``).

A SWORD deposit has to produce the same event stream an interactive submission
does, so these assert on submission state, not just on the response document.
"""

import arxiv.db.models as models
import pytest
from arxiv.db import Session
from lxml import etree

from submit_ce.sword.atom import ns
from submit_ce.sword.tests import client as sword_client
from submit_ce.sword.tests.client import ATOM_ENTRY_TYPE, basic_auth
from submit_ce.sword.tests.wrapper import Contributor, MediaLink, wrapper_entry

ZIP = b"PK\x03\x04 pretend this is a zip"
SUMMARY = "A concise abstract of the important findings herein"


def _deposit_media(client, depositor, collection="cs",
                   content_type="application/zip", payload=ZIP):
    response = client.post(
        f"/sword-app/{collection}-collection",
        content=payload,
        headers={"Authorization": basic_auth(depositor.nickname,
                                             depositor.password),
                 "Content-Type": content_type})
    assert response.status_code == 201, response.text
    return sword_client.edit_media_link(response.content)


def _wrapper(media_href, **overrides):
    fields = dict(
        title="A strangely unique title",
        summary=SUMMARY,
        primary_category="cs.CG",
        author_name="B. Editor",
        contributors=[Contributor("A. Genius", email="genius@example.org",
                                  affiliation="Institute of Irreproducible Results")],
        links=[MediaLink(media_href, "application/zip")],
    )
    fields.update(overrides)
    return wrapper_entry(**fields)


def _post_wrapper(client, depositor, document, collection="cs", **headers):
    request_headers = {"Authorization": basic_auth(depositor.nickname,
                                                   depositor.password),
                       "Content-Type": ATOM_ENTRY_TYPE}
    request_headers.update(headers)
    return client.post(f"/sword-app/{collection}-collection",
                       content=document, headers=request_headers)


@pytest.fixture
def media_href(client, depositor):
    return _deposit_media(client, depositor)


# ------------------------------------------------------------------ happy path


def test_wrapper_deposit_is_accepted(client, depositor, media_href):
    response = _post_wrapper(client, depositor, _wrapper(media_href))
    assert response.status_code == 202, response.text


def test_response_shape(client, depositor, media_href):
    response = _post_wrapper(client, depositor, _wrapper(media_href))
    root = etree.fromstring(response.content)

    assert root.findtext(ns.qname(ns.ATOM, "title")) == \
        "Accepted deposit wrapper to arXiv"
    assert root.findtext(ns.qname(ns.SWORD, "treatment")) == \
        "atom wrapper used to initiate ingestion into arXiv"
    assert root.findtext(ns.qname(ns.ATOM, "summary")) == SUMMARY


def test_location_and_links(client, depositor, media_href):
    response = _post_wrapper(client, depositor, _wrapper(media_href))
    sword_id = sword_client.sword_id(response.content)

    assert response.headers["Location"] == \
        f"https://arxiv.org/sword-app/getid/app/{sword_id}"
    assert sword_client.edit_link(response.content) == \
        f"https://arxiv.org/sword-app/edit/{sword_id}.atom"


def test_alternate_link_is_the_tracking_uri(client, depositor, media_href):
    """submit_sword.md:658-662. http, unlike the https edit links beside it."""
    response = _post_wrapper(client, depositor, _wrapper(media_href))
    sword_id = sword_client.sword_id(response.content)
    assert sword_client.alternate_link(response.content) == \
        f"http://arxiv.org/resolve/app/{sword_id}"


def test_primary_category_carries_a_real_category_and_no_text(client, depositor,
                                                              media_href):
    """Unlike the media entry, which names the collection (AtomPP.pm:1450-1462)."""
    response = _post_wrapper(client, depositor, _wrapper(media_href))
    primary = etree.fromstring(response.content).find(
        ns.qname(ns.ARXIV, "primary_category"))
    assert primary.get("term") == "http://arxiv.org/terms/arXiv/cs.CG"
    assert not (primary.text or "").strip()


def test_secondary_categories_are_echoed(client, depositor, media_href):
    response = _post_wrapper(client, depositor,
                             _wrapper(media_href, categories=["cs.AI"]))
    terms = [element.get("term") for element
             in etree.fromstring(response.content).iter(
                 ns.qname(ns.ATOM, "category"))]
    assert terms == ["http://arxiv.org/terms/arXiv/cs.AI"]


# ------------------------------------------------------------ submission state


def _submission(sword_id: int) -> models.Submission:
    tracking = Session.query(models.Tracking).filter_by(sword_id=sword_id).one()
    submission_id = int(tracking.paper_id.removeprefix("submit/"))
    return Session.get(models.Submission, submission_id)


def test_a_submission_is_created(client, depositor, media_href):
    response = _post_wrapper(client, depositor, _wrapper(media_href))
    submission = _submission(sword_client.sword_id(response.content))
    assert submission is not None


def test_metadata_reaches_the_submission(client, depositor, media_href):
    response = _post_wrapper(client, depositor, _wrapper(media_href))
    submission = _submission(sword_client.sword_id(response.content))

    assert submission.title == "A strangely unique title"
    assert submission.abstract == SUMMARY
    assert "A. Genius" in submission.authors


def test_affiliation_is_folded_into_the_author_string(client, depositor,
                                                      media_href):
    response = _post_wrapper(client, depositor, _wrapper(media_href))
    submission = _submission(sword_client.sword_id(response.content))
    assert "Institute of Irreproducible Results" in submission.authors


def test_depositor_is_recorded_as_the_proxy(client, depositor, media_href):
    """Legacy sets proxy => username (AtomPP.pm:1193)."""
    response = _post_wrapper(client, depositor, _wrapper(media_href))
    submission = _submission(sword_client.sword_id(response.content))
    assert submission.proxy == depositor.nickname


def test_contact_author_becomes_the_submitter_contact(client, depositor,
                                                      media_href):
    """The contributor's email, not the depositor's."""
    response = _post_wrapper(client, depositor, _wrapper(media_href))
    submission = _submission(sword_client.sword_id(response.content))
    assert submission.submitter_email == "genius@example.org"
    assert submission.submitter_name == "A. Genius"


def test_license_comes_from_the_registered_default(client, depositor,
                                                   media_href):
    response = _post_wrapper(client, depositor, _wrapper(media_href))
    submission = _submission(sword_client.sword_id(response.content))
    assert submission.license == \
        "http://arxiv.org/licenses/nonexclusive-distrib/1.0/"


def test_optional_metadata_reaches_the_submission(client, depositor, media_href):
    """The elements the legacy test helper emitted malformed, end to end."""
    response = _post_wrapper(client, depositor, _wrapper(
        media_href,
        comments=["24 pages, 2 figures"],
        journal_refs=["Nucl.Phys. B753 (2006) 295-312"],
        dois=["10.1016/j.nuclphysb.2006.07.013"],
        report_nums=["KUNS-2018", "YITP-06-19"]))
    submission = _submission(sword_client.sword_id(response.content))

    assert submission.comments == "24 pages, 2 figures"
    assert submission.journal_ref == "Nucl.Phys. B753 (2006) 295-312"
    assert submission.doi == "10.1016/j.nuclphysb.2006.07.013"
    assert submission.report_num == "KUNS-2018, YITP-06-19"


def test_secondary_classification_is_stored(client, depositor, media_href):
    response = _post_wrapper(client, depositor,
                             _wrapper(media_href, categories=["cs.AI"]))
    sword_id = sword_client.sword_id(response.content)
    submission = _submission(sword_id)
    categories = {c.category for c in Session.query(
        models.SubmissionCategory).filter_by(
            submission_id=submission.submission_id)}
    assert "cs.CG" in categories
    assert "cs.AI" in categories


# --------------------------------------------------------------------- tracking


def test_tracking_row_links_deposit_to_submission(client, depositor, media_href):
    """Written synchronously so /resolve/app answers as soon as 202 arrives."""
    response = _post_wrapper(client, depositor, _wrapper(media_href))
    sword_id = sword_client.sword_id(response.content)

    tracking = Session.query(models.Tracking).filter_by(sword_id=sword_id).one()
    assert tracking.paper_id.startswith("submit/")
    assert tracking.timestamp is not None


def test_submission_points_back_at_the_deposit(client, depositor, media_href):
    response = _post_wrapper(client, depositor, _wrapper(media_href))
    sword_id = sword_client.sword_id(response.content)
    assert _submission(sword_id).sword_id == sword_id


# ------------------------------------------------------------------- validation


def test_validation_failure_creates_nothing(client, depositor, media_href):
    """One save() per deposit, so a rejected wrapper leaves no partial state."""
    before = Session.query(models.Submission).count()
    response = _post_wrapper(client, depositor,
                             _wrapper(media_href, summary="too short"))
    assert response.status_code == 400
    assert b"<arxiv:errorcode>16384</arxiv:errorcode>" in response.content
    assert Session.query(models.Submission).count() == before


def test_primary_category_must_belong_to_the_posted_collection(client, depositor,
                                                               media_href):
    """AtomPP.pm:983-991.

    The fixture depositor holds physics, so this is EVPCT for the
    category/collection mismatch, not EAUTH for a permission failure.
    """
    response = _post_wrapper(client, depositor,
                             _wrapper(media_href, primary_category="cs.CG"),
                             collection="physics")
    assert response.status_code == 400
    assert b"<arxiv:errorcode>2048</arxiv:errorcode>" in response.content
    assert b"no primary category &#39;cs.CG&#39; in collection &#39;physics&#39;" \
        in response.content or b"in collection 'physics'" in response.content


def test_wrapper_referencing_no_media_is_enrel(client, depositor):
    response = _post_wrapper(client, depositor, _wrapper("", links=[]))
    assert response.status_code == 400
    assert b"<arxiv:errorcode>8388608</arxiv:errorcode>" in response.content


def test_wrapper_referencing_an_unknown_deposit_is_enmdi(client, depositor):
    document = _wrapper("https://arxiv.org/sword-app/edit/10039999")
    response = _post_wrapper(client, depositor, document)
    assert response.status_code == 400
    assert b"<arxiv:errorcode>524288</arxiv:errorcode>" in response.content


def test_x_on_behalf_of_overrides_the_contributor_contact(client, depositor,
                                                          media_href):
    response = _post_wrapper(
        client, depositor, _wrapper(media_href),
        **{"X-On-Behalf-Of": '"A. Scientist" <scientist@example.org>'})
    assert response.status_code == 202
    submission = _submission(sword_client.sword_id(response.content))
    assert submission.submitter_email == "scientist@example.org"


# ----------------------------------------------------------------------- no-op


def test_no_op_wrapper_validates_without_creating_anything(client, depositor,
                                                           media_href):
    """Plan decision 4: a true no-op, unlike legacy (AtomPP.pm:1280-1291)."""
    before = Session.query(models.Submission).count()
    response = _post_wrapper(client, depositor, _wrapper(media_href),
                             **{"X-No-Op": "True"})

    assert response.status_code == 200
    assert "Location" not in response.headers
    assert Session.query(models.Submission).count() == before
    assert Session.query(models.Tracking).count() == 0


def test_no_op_still_reports_validation_failures(client, depositor, media_href):
    response = _post_wrapper(client, depositor,
                             _wrapper(media_href, summary="short"),
                             **{"X-No-Op": "True"})
    assert response.status_code == 400


def test_verbose_wrapper_describes_release_pending(client, depositor, media_href):
    response = _post_wrapper(client, depositor, _wrapper(media_href),
                             **{"X-Verbose": "True"})
    root = etree.fromstring(response.content)
    assert root.findtext(ns.qname(ns.SWORD, "verboseDescription")) == \
        "release pending"
