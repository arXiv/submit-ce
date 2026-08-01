"""Deposit tracking via ``GET /resolve/app/<sword_id>``.

Reference: ``arxiv-submit/lib/arXiv/Controller/Sword.pm:23-103`` for the state
machine and ``submit_sword.md:637-706`` for the documented statuses and examples.
"""

from datetime import datetime, timezone

import arxiv.db.models as models
import pytest
from arxiv.db import Session
from lxml import etree

from submit_ce.sword import tracking
from submit_ce.sword.tests import client as sword_client
from submit_ce.sword.tests.client import ATOM_ENTRY_TYPE, basic_auth
from submit_ce.sword.tests.wrapper import Contributor, MediaLink, wrapper_entry

ZIP = b"PK\x03\x04 pretend this is a zip"
SITE = "arxiv.org"


def _add_tracking(sword_id: int, paper_id: str) -> None:
    Session.add(models.Tracking(sword_id=sword_id, paper_id=paper_id,
                                timestamp=datetime.now(timezone.utc)))
    Session.commit()


def _get(client, sword_id):
    return client.get(f"/resolve/app/{sword_id}")


def _tree(response):
    return etree.fromstring(response.content)


def _field(response, name):
    return _tree(response).findtext(name)


# ---------------------------------------------------------------- document shape


def test_root_element_is_deposit(client, sword_db):
    _add_tracking(10030146, "submit/1")
    assert _tree(_get(client, 10030146)).tag == "deposit"


def test_content_type_matches_legacy(client, sword_db):
    """Controller/Sword.pm:102, quoted charset included."""
    _add_tracking(10030146, "submit/1")
    assert _get(client, 10030146).headers["content-type"] == \
        'application/xml; charset="utf-8"'


def test_tracking_id_is_echoed(client, sword_db):
    """submit_sword.md:670 -- the document repeats its own URI."""
    _add_tracking(10030146, "submit/1")
    assert _field(_get(client, 10030146), "tracking_id") == \
        "http://arxiv.org/resolve/app/10030146"


def test_status_is_always_present(client, sword_db):
    """The manual guarantees a <status> in every response (submit_sword.md:683)."""
    assert _field(_get(client, 999999), "status")


def test_no_authentication_required(client, sword_db):
    """sword.conf gates /sword-app but not /resolve."""
    _add_tracking(10030146, "submit/1")
    response = client.get("/resolve/app/10030146")
    assert response.status_code == 200
    assert "WWW-Authenticate" not in response.headers


# ------------------------------------------------------------------- unknown


def test_unknown_deposit_id(client, sword_db):
    """The id may name a media deposit rather than a wrapper."""
    response = _get(client, 999999)
    assert _field(response, "status") == "unknown"
    assert "may belong to a media deposit" in _field(response, "error")


def test_missing_submission_is_unknown(client, sword_db):
    """A tracking row pointing at a submission that is not there."""
    _add_tracking(10030146, "submit/424242")
    response = _get(client, 10030146)
    assert _field(response, "status") == "unknown"
    assert _field(response, "error") == "Submission not found"


def test_published_paper_without_a_document_is_unknown(client, sword_db):
    _add_tracking(10030146, "1234.56789")
    response = _get(client, 10030146)
    assert _field(response, "status") == "unknown"
    assert _field(response, "error") == \
        "No valid document found. Please contact arXiv admins."


# -------------------------------------------------------------------- failed


def test_failed_deposit(client, sword_db):
    """Controller/Sword.pm:49-52. Note 'failed' is not in the manual's list."""
    _add_tracking(10030146, "failed - conflict")
    response = _get(client, 10030146)
    assert _field(response, "status") == "failed"
    assert _field(response, "error") == "conflicting submission active"


# ----------------------------------------------------------------- published


def test_published_deposit_reports_the_arxiv_id(client, sword_db):
    """submit_sword.md:674-681."""
    Session.add(models.Document(paper_id="1003.9876", title="A paper",
                                submitter_email="a@example.org"))
    Session.commit()
    _add_tracking(10030146, "1003.9876")

    response = _get(client, 10030146)
    assert _field(response, "status") == "published"
    assert _field(response, "arxiv_id") == "1003.9876"


# ------------------------------------------------------- end to end from a deposit


@pytest.fixture
def deposited(client, depositor):
    """A real wrapper deposit, returning its sword id."""
    media = client.post(
        "/sword-app/cs-collection", content=ZIP,
        headers={"Authorization": basic_auth(depositor.nickname,
                                             depositor.password),
                 "Content-Type": "application/zip"})
    assert media.status_code == 201
    href = sword_client.edit_media_link(media.content)

    document = wrapper_entry(
        title="A strangely unique title",
        summary="A concise abstract of the important findings herein",
        primary_category="cs.CG",
        author_name="B. Editor",
        contributors=[Contributor("A. Genius", email="genius@example.org")],
        links=[MediaLink(href, "application/zip")])

    wrapper = client.post(
        "/sword-app/cs-collection", content=document,
        headers={"Authorization": basic_auth(depositor.nickname,
                                             depositor.password),
                 "Content-Type": ATOM_ENTRY_TYPE})
    assert wrapper.status_code == 202, wrapper.text
    return sword_client.sword_id(wrapper.content)


def test_tracking_works_immediately_after_a_deposit(client, deposited):
    """The whole point of writing the tracking row synchronously."""
    response = _get(client, deposited)
    assert response.status_code == 200
    assert _field(response, "submission_id")


def test_alternate_link_from_the_deposit_resolves(client, depositor, deposited):
    """The URI the 202 response told the client to use."""
    assert _field(_get(client, deposited), "tracking_id") == \
        f"http://arxiv.org/resolve/app/{deposited}"


def test_a_fresh_deposit_is_not_yet_published(client, deposited):
    """Finalization waits on compile, so it is still in progress."""
    status = _field(_get(client, deposited), "status")
    assert status in ("submitted", "incomplete", "on hold")
    assert _field(_get(client, deposited), "arxiv_id") is None


# ----------------------------------------------------------- status mapping


class _FakeSubmission:
    def __init__(self, announced=False, on_hold=False, finalized=True,
                 arxiv_id=None):
        self.is_announced = announced
        self.is_on_hold = on_hold
        self.is_finalized = finalized
        self.arxiv_id = arxiv_id


@pytest.mark.parametrize("submission,expected", [
    (_FakeSubmission(announced=True, arxiv_id="1003.9876"), "published"),
    (_FakeSubmission(on_hold=True), "on hold"),
    (_FakeSubmission(finalized=True), "submitted"),
    (_FakeSubmission(finalized=False), "incomplete"),
])
def test_status_mapping(submission, expected):
    assert tracking._status_for(submission) == expected


def test_hold_takes_precedence_over_submitted():
    """A held submission is still SUBMITTED in submit-ce's model."""
    held = _FakeSubmission(on_hold=True, finalized=True)
    assert tracking._status_for(held) == "on hold"


def test_every_status_is_one_the_manual_documents_or_legacy_emits():
    documented = {"submitted", "published", "on hold", "incomplete", "unknown"}
    assert tracking.FAILED not in documented, "failed is the undocumented one"
    for status in (tracking.SUBMITTED, tracking.PUBLISHED, tracking.ON_HOLD,
                   tracking.INCOMPLETE, tracking.UNKNOWN):
        assert status in documented


# ------------------------------------------------------------------- rendering


def test_absent_fields_are_omitted():
    status = tracking.DepositStatus(tracking_id="http://arxiv.org/resolve/app/1",
                                    status="submitted")
    root = etree.fromstring(tracking.render_deposit(status))
    assert [child.tag for child in root] == ["tracking_id", "status"]


def test_all_fields_render_in_a_stable_order():
    """Legacy iterates a Perl hash, so its order varies; ours does not."""
    status = tracking.DepositStatus(
        tracking_id="http://arxiv.org/resolve/app/1", status="submitted",
        submission_id=7, arxiv_id="1003.9876", error="oops",
        autotex_log_b64="bG9n")
    root = etree.fromstring(tracking.render_deposit(status))
    assert [child.tag for child in root] == [
        "tracking_id", "status", "submission_id", "arxiv_id", "error",
        "autotex_log_b64"]


def test_document_has_an_xml_declaration():
    status = tracking.DepositStatus(tracking_id="x", status="unknown")
    assert tracking.render_deposit(status).startswith(b"<?xml")


# ------------------------------------------------------------------ compile log


class _FakeLogFile:
    """The `FileObj` shape `_compile_log` uses: just ``open()``."""

    def __init__(self, data: bytes):
        self.data = data

    def open(self, mode: str = "rb"):
        import io
        return io.BytesIO(self.data)


class _StoreWithLog:
    """A file store that actually holds a compile log.

    `MockFileStore` inherits `NullFileStore`'s compile-log stubs, where
    ``does_compile_log_exist`` is always False, so it cannot exercise this path.
    """

    def __init__(self, data: bytes):
        self.data = data

    def does_compile_log_exist(self, _submission_id: str) -> bool:
        return True

    def get_compile_log(self, _submission_id: str) -> _FakeLogFile:
        return _FakeLogFile(self.data)


def test_compile_log_is_attached_when_present(client, deposited, sword_app):
    """The undocumented autotex_log_b64 extension (Controller/Sword.pm:44-52)."""
    import base64

    original = sword_app.state.api.store
    sword_app.state.api.store = _StoreWithLog(b"latex said no")
    try:
        response = _get(client, deposited)
    finally:
        sword_app.state.api.store = original

    encoded = _field(response, "autotex_log_b64")
    assert encoded is not None
    assert base64.b64decode(encoded) == b"latex said no"


def test_compile_log_absent_when_there_is_none(client, deposited):
    assert _field(_get(client, deposited), "autotex_log_b64") is None


def test_compile_log_failure_does_not_break_tracking(client, deposited,
                                                     sword_app):
    """Best-effort, like the Perl's try/catch."""
    class _Broken:
        def does_compile_log_exist(self, _):
            raise RuntimeError("bucket on fire")

    original = sword_app.state.api.store
    sword_app.state.api.store = _Broken()
    try:
        response = _get(client, deposited)
    finally:
        sword_app.state.api.store = original

    assert response.status_code == 200
    assert _field(response, "status")
