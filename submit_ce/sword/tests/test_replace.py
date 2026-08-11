"""Replacement: ``PUT`` a wrapper to an ``edit`` href.

``AtomPP.pm:413-531`` for the identifier ladder and ownership, and
``submit_sword.md:707-781`` for the documented behaviour. A replacement creates a new
*version* of an announced paper, and cannot change its classification.
"""

from datetime import datetime, timezone

import arxiv.db.models as models
import pytest
from arxiv.db import Session
from lxml import etree

from submit_ce.sword import replace as sword_replace
from submit_ce.sword.atom import ns
from submit_ce.domain.exceptions import NoSuchSubmission
from submit_ce.sword.errors import SwordFault
from submit_ce.sword.tests import client as sword_client
from submit_ce.sword.tests.client import ATOM_ENTRY_TYPE, basic_auth
from submit_ce.sword.tests.wrapper import Contributor, MediaLink, wrapper_entry

ZIP = b"PK\x03\x04 pretend this is a zip"
SUMMARY = "A concise abstract of the important findings herein"
PAPER_ID = "2607.00001"


def _auth(depositor):
    return {"Authorization": basic_auth(depositor.nickname, depositor.password)}


def _wrapper(media_href, **overrides):
    fields = dict(
        title="A strangely unique title",
        summary=SUMMARY,
        primary_category="cs.CG",
        author_name="B. Editor",
        contributors=[Contributor("A. Genius", email="genius@example.org")],
        links=[MediaLink(media_href, "application/zip")],
    )
    fields.update(overrides)
    return wrapper_entry(**fields)


@pytest.fixture
def media_href(client, depositor):
    response = client.post(
        "/sword-app/cs-collection", content=ZIP,
        headers={**_auth(depositor), "Content-Type": "application/zip"})
    assert response.status_code == 201
    return sword_client.edit_media_link(response.content)


@pytest.fixture
def announced(client, depositor, media_href):
    """A deposited submission, marked announced so it can be replaced.

    Mirrors how `submit_ce.ui.conftest`'s ``published_submission`` fakes
    announcement: set the legacy status, attach a Document, and register the
    depositor as a paper owner.
    """
    response = client.post(
        "/sword-app/cs-collection", content=_wrapper(media_href),
        headers={**_auth(depositor), "Content-Type": ATOM_ENTRY_TYPE})
    assert response.status_code == 202, response.text
    sword_id = sword_client.sword_id(response.content)

    tracking = Session.query(models.Tracking).filter_by(sword_id=sword_id).one()
    submission_id = int(tracking.paper_id.removeprefix("submit/"))

    document = models.Document(paper_id=PAPER_ID,
                               title="A strangely unique title",
                               submitter_email="genius@example.org")
    Session.add(document)
    Session.flush()

    submission = Session.get(models.Submission, submission_id)
    submission.status = 7            # announced
    submission.doc_paper_id = PAPER_ID
    submission.document_id = document.document_id
    Session.add(models.PaperOwner(document_id=document.document_id,
                                  user_id=depositor.user_id,
                                  date=datetime.now(timezone.utc),
                                  valid=1, flag_author=1, flag_auto=0))
    # Publication rewrites the tracking row's paper_id from submit/<id> to the
    # real paper id (Controller/Sword.pm:29-31 reads it back that way). Doing the
    # same here is what makes the rel="edit" href resolvable, as it would be in
    # production.
    tracking.paper_id = PAPER_ID
    Session.commit()

    return {"sword_id": sword_id, "submission_id": submission_id,
            "paper_id": PAPER_ID, "document_id": document.document_id}


def _put(client, depositor, target, document, **headers):
    request_headers = {**_auth(depositor), "Content-Type": ATOM_ENTRY_TYPE}
    request_headers.update(headers)
    return client.put(f"/sword-app/edit/{target}", content=document,
                      headers=request_headers)


# ------------------------------------------------------- identifier resolution


def test_resolve_a_new_style_paper_id(sword_db):
    assert sword_replace.resolve_target(Session, "0708.0123") == "0708.0123"


def test_resolve_a_five_digit_paper_id(sword_db):
    assert sword_replace.resolve_target(Session, "2607.00001") == "2607.00001"


def test_resolve_an_old_style_paper_id(sword_db):
    """submit_sword.md:779."""
    assert sword_replace.resolve_target(Session, "cond-mat/9904123") == \
        "cond-mat/9904123"


def test_version_suffix_is_stripped(sword_db):
    """A replacement always makes the next version (AtomPP.pm:442)."""
    assert sword_replace.resolve_target(Session, "0708.0123v2") == "0708.0123"


def test_resolve_a_deposit_atom_href(sword_db):
    """The rel="edit" href resolves via arXiv_tracking (AtomPP.pm:432-440)."""
    Session.add(models.Tracking(sword_id=26070001, paper_id="0708.0123",
                                timestamp=datetime.now(timezone.utc)))
    Session.commit()
    assert sword_replace.resolve_target(Session, "26070001.atom") == "0708.0123"


def test_empty_target_is_enoid(sword_db):
    with pytest.raises(SwordFault) as excinfo:
        sword_replace.resolve_target(Session, "")
    assert excinfo.value.error.mnemonic == "ENOID"


def test_a_pending_submission_cannot_be_replaced(sword_db):
    """EPSUB (AtomPP.pm:444-449) -- a paper must be announced first."""
    Session.add(models.Tracking(sword_id=26070002, paper_id="submit/1234567",
                                timestamp=datetime.now(timezone.utc)))
    Session.commit()
    with pytest.raises(SwordFault) as excinfo:
        sword_replace.resolve_target(Session, "26070002.atom")
    assert excinfo.value.error.mnemonic == "EPSUB"
    assert "cannot be replaced" in excinfo.value.summary


@pytest.mark.parametrize("target", ["nonsense", "12.34", "abc/123"])
def test_an_unusable_identifier_is_envid(sword_db, target):
    with pytest.raises(SwordFault) as excinfo:
        sword_replace.resolve_target(Session, target)
    assert excinfo.value.error.mnemonic == "ENVID"


def test_an_unknown_deposit_atom_is_envid(sword_db):
    with pytest.raises(SwordFault) as excinfo:
        sword_replace.resolve_target(Session, "99999999.atom")
    assert excinfo.value.error.mnemonic == "ENVID"


# ----------------------------------------------------------------- ownership


def test_paper_owners_are_resolved_to_nicknames(client, depositor, announced):
    assert sword_replace.paper_owners(Session, PAPER_ID) == [depositor.nickname]


def test_no_owners_for_an_unknown_paper(sword_db):
    assert sword_replace.paper_owners(Session, "9999.99999") == []


def test_require_owner_refuses_a_stranger(client, depositor, announced):
    with pytest.raises(SwordFault) as excinfo:
        sword_replace.require_owner(Session, PAPER_ID, "somebody-else")
    assert excinfo.value.error.mnemonic == "ENOWN"


def test_ownership_is_case_sensitive(client, depositor, announced):
    """submit_sword.md:726-727 says so explicitly."""
    with pytest.raises(SwordFault):
        sword_replace.require_owner(Session, PAPER_ID,
                                    depositor.nickname.upper())


# ------------------------------------------------------------------ happy path


def test_replacement_is_accepted(client, depositor, announced, media_href):
    response = _put(client, depositor, PAPER_ID, _wrapper(media_href))
    assert response.status_code == 202, response.text


def test_replacement_creates_a_new_version_row(client, depositor, announced,
                                               media_href):
    """submit_sword.md:711-717 -- a new version number is assigned.

    A replacement is "mainly an incremented version number. This requires a new
    row" (``legacy_implementation/db.py:489-491``), so the original row keeps
    version 1 and a ``rep`` row appears at version 2. Previous versions stay
    accessible, which is what the manual promises (``submit_sword.md:716-717``).
    """
    response = _put(client, depositor, PAPER_ID, _wrapper(media_href))
    assert response.status_code == 202, response.text

    Session.expire_all()
    rows = Session.query(models.Submission).filter_by(
        doc_paper_id=PAPER_ID).order_by(models.Submission.version).all()

    assert [(row.type, row.version) for row in rows] == [("new", 1), ("rep", 2)]
    assert Session.get(models.Submission,
                       announced["submission_id"]).version == 1


def test_replacement_row_records_the_client_address(client, depositor, announced,
                                                    media_href):
    """``remote_addr`` is NOT NULL and was omitted from the replacement row.

    ``db.py`` set it for withdrawal and JREF rows but not for replacements, because
    ``update_from_submission`` only fills it on the initial row
    (``models.py:365-369``). On MySQL that silently lost the depositor's address;
    on sqlite it failed the insert outright.
    """
    assert _put(client, depositor, PAPER_ID,
                _wrapper(media_href)).status_code == 202

    Session.expire_all()
    replacement = Session.query(models.Submission).filter_by(
        doc_paper_id=PAPER_ID, version=2).one()
    assert replacement.remote_addr


def test_replacement_response_says_replacement(client, depositor, announced,
                                               media_href):
    """AtomPP.pm:1382 uses a different verbose description."""
    response = _put(client, depositor, PAPER_ID, _wrapper(media_href),
                    **{"X-Verbose": "True"})
    root = etree.fromstring(response.content)
    assert root.findtext(ns.qname(ns.SWORD, "verboseDescription")) == \
        "replacement being processed"


def test_replacement_via_the_edit_atom_href(client, depositor, announced,
                                            media_href):
    """The path the manual tells depositors to use (submit_sword.md:746-754).

    PUT to the ``rel="edit"`` href of the original wrapper, which resolves through
    ``arXiv_tracking`` to the announced paper id.
    """
    response = _put(client, depositor, f"{announced['sword_id']}.atom",
                    _wrapper(media_href))
    assert response.status_code == 202, response.text


def test_replacement_gets_a_new_deposit_id(client, depositor, announced,
                                           media_href):
    response = _put(client, depositor, PAPER_ID, _wrapper(media_href))
    assert sword_client.sword_id(response.content) != announced["sword_id"]


def test_replacement_location_header(client, depositor, announced, media_href):
    response = _put(client, depositor, PAPER_ID, _wrapper(media_href))
    sword_id = sword_client.sword_id(response.content)
    assert response.headers["Location"] == \
        f"https://arxiv.org/sword-app/getid/app/{sword_id}"


# ------------------------------------------------------------------ refusals


def test_replacement_by_a_non_owner_is_enown(client, depositor, announced,
                                             unlicensed_depositor, media_href):
    Session.add(models.SwordLicense(
        user_id=unlicensed_depositor.user_id,
        license="http://arxiv.org/licenses/nonexclusive-distrib/1.0/",
        updated=datetime.now(timezone.utc)))
    Session.commit()

    response = _put(client, unlicensed_depositor, PAPER_ID, _wrapper(media_href))
    assert response.status_code == 400
    assert b"<arxiv:errorcode>134217728</arxiv:errorcode>" in response.content


def test_replacement_requires_an_atom_content_type(client, depositor, announced,
                                                   media_href):
    """AtomPP.pm:482-488 -- 415 with a message naming the required type."""
    response = _put(client, depositor, PAPER_ID, ZIP,
                    **{"Content-Type": "application/zip"})
    assert response.status_code == 415
    assert b"application/atom+xml" in response.content


def test_replacement_may_not_change_the_categories(client, depositor, announced,
                                                   media_href):
    """ERCTS -- classification cannot change (submit_sword.md:780)."""
    response = _put(client, depositor, PAPER_ID,
                    _wrapper(media_href, categories=["cs.AI"]))
    assert response.status_code == 400
    assert b"<arxiv:errorcode>8194</arxiv:errorcode>" in response.content


def test_replacement_with_no_categories_is_accepted(client, depositor, announced,
                                                    media_href):
    """"no category elements, or a set that matches"."""
    response = _put(client, depositor, PAPER_ID, _wrapper(media_href))
    assert response.status_code == 202


def test_replacement_requires_credentials(client, announced, media_href):
    response = client.put(f"/sword-app/edit/{PAPER_ID}",
                          content=_wrapper(media_href),
                          headers={"Content-Type": ATOM_ENTRY_TYPE})
    assert response.status_code == 401


def test_replacement_of_an_unknown_paper_is_envid(client, depositor, media_href):
    response = _put(client, depositor, "9999.99999", _wrapper(media_href))
    assert response.status_code == 400
    assert b"<arxiv:errorcode>" in response.content


# ----------------------------------------------------------------------- no-op


def test_no_op_replacement_changes_nothing(client, depositor, announced,
                                           media_href):
    before = Session.get(models.Submission, announced["submission_id"]).version

    response = _put(client, depositor, PAPER_ID, _wrapper(media_href),
                    **{"X-No-Op": "True"})
    assert response.status_code == 200
    assert "Location" not in response.headers

    Session.expire_all()
    assert Session.get(models.Submission,
                       announced["submission_id"]).version == before


# ------------------------------------------------------------------ edge cases


def test_paper_with_a_document_but_no_owners(sword_db):
    """A document exists but nobody has claimed it, so nobody may replace it."""
    Session.add(models.Document(paper_id="0708.0123", title="Orphan",
                                submitter_email="a@example.org"))
    Session.commit()

    assert sword_replace.paper_owners(Session, "0708.0123") == []
    with pytest.raises(SwordFault) as excinfo:
        sword_replace.require_owner(Session, "0708.0123", "vtex")
    assert excinfo.value.error.mnemonic == "ENOWN"


def test_existing_categories_of_an_unknown_paper(sword_db):
    assert sword_replace.existing_categories(Session, "9999.99999") == []


def test_put_to_a_paper_with_no_submission_row_is_envid(client, depositor,
                                                        media_href):
    """A document and owner exist, but no submission row produced it.

    Possible for papers predating submit-ce's tables; a replacement needs the
    submission to version.
    """
    document = models.Document(paper_id="0708.0123", title="Ancient",
                               submitter_email="a@example.org")
    Session.add(document)
    Session.flush()
    Session.add(models.PaperOwner(document_id=document.document_id,
                                  user_id=depositor.user_id,
                                  date=datetime.now(timezone.utc),
                                  valid=1, flag_author=1, flag_auto=0))
    Session.commit()

    response = _put(client, depositor, "0708.0123", _wrapper(media_href))
    assert response.status_code == 400
    assert b"<arxiv:errorcode>1073741824</arxiv:errorcode>" in response.content
    assert b"no submission for" in response.content


def test_replacement_honours_x_on_behalf_of(client, depositor, announced,
                                            media_href):
    """The header disambiguates the contact author on a replacement too."""
    response = _put(client, depositor, PAPER_ID, _wrapper(media_href),
                    **{"X-On-Behalf-Of": '"A. Scientist" <scientist@example.org>'})
    assert response.status_code == 202, response.text

    Session.expire_all()
    replacement = Session.query(models.Submission).filter_by(
        doc_paper_id=PAPER_ID, version=2).one()
    assert replacement.submitter_email == "scientist@example.org"


# ------------------------------------------------------- a version already in flight


EPSUB_CODE = b"<arxiv:errorcode>4294967296</arxiv:errorcode>"


def test_a_second_replacement_is_refused_while_the_first_is_open(
        client, depositor, announced, media_href):
    """One open version at a time.

    A replacement creates an unannounced version 2. Until that is announced there is
    nothing to build version 3 on, so the deposit is refused rather than attempted.

    Legacy accepted the second deposit and reported the conflict afterwards, by
    writing ``'failed - conflict'`` into ``arXiv_tracking`` from the processing fork
    (``AtomPP.pm:1310-1313``). Deposits happen inside the request here, so the
    depositor is told immediately.
    """
    assert _put(client, depositor, PAPER_ID,
                _wrapper(media_href)).status_code == 202

    second = _put(client, depositor, PAPER_ID, _wrapper(media_href))
    assert second.status_code == 400
    assert EPSUB_CODE in second.content
    assert b"already has submission" in second.content


def test_the_refusal_does_not_create_a_third_version(client, depositor,
                                                     announced, media_href):
    """The check runs before any event is saved."""
    _put(client, depositor, PAPER_ID, _wrapper(media_href))
    _put(client, depositor, PAPER_ID, _wrapper(media_href))

    Session.expire_all()
    versions = sorted(row.version for row in Session.query(models.Submission)
                      .filter_by(doc_paper_id=PAPER_ID))
    assert versions == [1, 2]


@pytest.mark.xfail(strict=True, raises=NoSuchSubmission, reason=(
    "Separate pre-existing defect, not the conflict check: a replacement's new row "
    "gets no event rows of its own. `_new_dbevent` stamps each event with "
    "`event.submission_id` (db.py:650), which for `CreateSubmissionVersion` is the "
    "submission being versioned -- so all events stay under the original id and "
    "`get_events()` on the new row raises. Shared persistence, so the UI's "
    "replacement flow versions an already-replaced paper no better than SWORD does. "
    "This test asserts the behaviour we want and will start passing when that is "
    "fixed."))
def test_a_replacement_is_allowed_again_once_the_version_is_announced(
        client, depositor, announced, media_href):
    """The conflict is transient, not a permanent block on the paper."""
    assert _put(client, depositor, PAPER_ID,
                _wrapper(media_href)).status_code == 202

    Session.expire_all()
    version_2 = Session.query(models.Submission).filter_by(
        doc_paper_id=PAPER_ID, version=2).one()
    version_2.status = 7                      # announced
    Session.commit()

    third = _put(client, depositor, PAPER_ID, _wrapper(media_href))
    assert third.status_code == 202, third.text

    Session.expire_all()
    assert Session.query(models.Submission).filter_by(
        doc_paper_id=PAPER_ID, version=3).one_or_none() is not None


def test_a_deleted_version_does_not_block_a_replacement(client, depositor,
                                                        announced, media_href):
    """``is_active()`` excludes the deleted statuses (``models.py:92-95``)."""
    assert _put(client, depositor, PAPER_ID,
                _wrapper(media_href)).status_code == 202

    Session.expire_all()
    Session.query(models.Submission).filter_by(
        doc_paper_id=PAPER_ID, version=2).one().status = 10   # user deleted
    Session.commit()

    assert _put(client, depositor, PAPER_ID,
                _wrapper(media_href)).status_code == 202


def test_ownership_is_checked_before_the_conflict_is_disclosed(
        client, plain_user, depositor, announced, media_href):
    """A non-owner must not learn that a version is open.

    ``plain_user`` cannot deposit at all, so the gate it hits is EAUTH -- the point
    is that it is not EPSUB.
    """
    _put(client, depositor, PAPER_ID, _wrapper(media_href))

    response = _put(client, plain_user, PAPER_ID, _wrapper(media_href))
    assert response.status_code == 401
    assert EPSUB_CODE not in response.content


# ------------------------------------------------- announced_submission_id filtering


def test_announced_submission_id_skips_an_unannounced_version(
        client, depositor, announced, media_href, sword_db):
    """The regression behind the original bug.

    Before the status filter this returned the highest ``submission_id`` for the
    paper, which after one replacement is the unannounced version 2 -- and building a
    version on that raised `NoSuchSubmission`.
    """
    _put(client, depositor, PAPER_ID, _wrapper(media_href))
    Session.expire_all()

    announced_row = Session.query(models.Submission).filter_by(
        doc_paper_id=PAPER_ID, version=1).one()
    unannounced = Session.query(models.Submission).filter_by(
        doc_paper_id=PAPER_ID, version=2).one()

    resolved = sword_replace.announced_submission_id(Session, PAPER_ID)
    assert resolved == announced_row.submission_id
    assert resolved != unannounced.submission_id


def test_pending_submission_id_is_none_when_nothing_is_open(
        client, depositor, announced, sword_db):
    assert sword_replace.pending_submission_id(Session, PAPER_ID) is None


def test_pending_submission_id_finds_the_open_version(client, depositor,
                                                      announced, media_href,
                                                      sword_db):
    _put(client, depositor, PAPER_ID, _wrapper(media_href))
    Session.expire_all()

    expected = Session.query(models.Submission).filter_by(
        doc_paper_id=PAPER_ID, version=2).one().submission_id
    assert sword_replace.pending_submission_id(Session, PAPER_ID) == expected


def test_an_oversize_replacement_is_413(client, depositor, announced,
                                        media_href):
    """PUT carries a wrapper too, so it is capped on the same limit."""
    from submit_ce.sword.deposits import max_deposit_bytes

    padding = "z" * max_deposit_bytes()
    document = ('<?xml version="1.0"?><entry xmlns="http://www.w3.org/2005/Atom">'
                f"<title>{padding}</title></entry>").encode()

    response = _put(client, depositor, PAPER_ID, document)
    assert response.status_code == 413
    assert b"<arxiv:errorcode>34359738368</arxiv:errorcode>" in response.content
