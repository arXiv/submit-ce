"""Turning a validated wrapper into events.

`metadata_events` and `upload_events` are pure functions over a
`WrapperMetadata`, so the event sequence can be asserted without a database.
"""

import pytest

from submit_ce.domain.event import (
    AddSecondaryClassification,
    ConfirmPolicy,
    CreateSubmission,
    SetAbstract,
    SetACMClassification,
    SetAuthors,
    SetComments,
    SetDOI,
    SetJournalReference,
    SetLicense,
    SetMSCClassification,
    SetPrimaryClassification,
    SetProxyInformation,
    SetReportNumber,
    SetTitle,
)
from submit_ce.domain.agent import HttpClient, PublicUser
from submit_ce.domain.event.file import UploadArchive, UploadFiles
from submit_ce.sword.atom.parse import WrapperMetadata
from submit_ce.sword.deposits import InMemoryDepositStore
from submit_ce.sword.ingest import (
    license_name_for,
    metadata_events,
    upload_events,
)

LICENSE = "http://arxiv.org/licenses/nonexclusive-distrib/1.0/"

CREATOR = PublicUser(user_id="55596", name="vtex", email="vtex@example.org",
                     endorsements=["cs.*"])
CLIENT = HttpClient(remote_addr="127.0.0.1", version="arXiv SWORD demo 1.1")


def _metadata(**overrides) -> WrapperMetadata:
    fields = dict(
        title="A strangely unique title",
        summary="A concise abstract of the important findings herein",
        authors=["A. Genius", "S. Clown (Circus)"],
        contact_name="A. Genius",
        contact_email="genius@example.org",
        primary_category="cs.CG",
        categories=["cs.CG"],
        media_ids=["10030146"],
    )
    fields.update(overrides)
    return WrapperMetadata(**fields)


def _events(**overrides):
    return metadata_events(_metadata(**overrides), creator=CREATOR,
                           client=CLIENT, depositor="vtex",
                           license_uri=LICENSE)


def _types(events):
    return [type(event) for event in events]


# ---------------------------------------------------------------- event sequence


def test_minimal_event_sequence():
    types = _types(_events())
    assert types == [CreateSubmission, SetProxyInformation, ConfirmPolicy,
                     SetLicense, SetTitle, SetAbstract, SetAuthors,
                     SetPrimaryClassification]


def test_create_submission_comes_first():
    """save() needs it first to allocate a submission id."""
    assert isinstance(_events()[0], CreateSubmission)


def test_proxy_information_carries_all_three_legacy_fields():
    """proxy, submitter_name and submitter_email in one event."""
    event = next(e for e in _events() if isinstance(e, SetProxyInformation))
    assert event.proxy_name == "vtex"
    assert event.proxied_name == "A. Genius"
    assert event.proxied_email == "genius@example.org"


def test_policy_is_accepted_on_the_depositors_behalf():
    """Acceptance is established out of band; see SWORD_AGREEMENT_ID."""
    event = next(e for e in _events() if isinstance(e, ConfirmPolicy))
    assert event.agreement_id == 1


def test_license_comes_from_the_registered_default():
    event = next(e for e in _events() if isinstance(e, SetLicense))
    assert event.license_uri == LICENSE
    assert event.license_name


def test_authors_are_supplied_as_a_display_string():
    """SWORD carries free-text names, so authors_display is set directly."""
    event = next(e for e in _events() if isinstance(e, SetAuthors))
    assert event.authors_display == "A. Genius, S. Clown (Circus)"
    assert [a.display for a in event.authors] == ["A. Genius", "S. Clown (Circus)"]


def test_secondaries_become_one_event_each():
    events = _events(categories=["cs.CG", "cs.AI", "cs.DL"])
    secondaries = [e for e in events if isinstance(e, AddSecondaryClassification)]
    assert [e.category for e in secondaries] == ["cs.AI", "cs.DL"]


def test_primary_is_not_repeated_as_a_secondary():
    events = _events(categories=["cs.CG"])
    assert not any(isinstance(e, AddSecondaryClassification) for e in events)


# --------------------------------------------------------------- optional fields


@pytest.mark.parametrize("field_name,event_class,value", [
    ("comments", SetComments, "24 pages"),
    ("journal_ref", SetJournalReference, "Nucl.Phys. B753 (2006) 295"),
    ("doi", SetDOI, "10.1016/j.nuclphysb.2006.07.013"),
    ("report_num", SetReportNumber, "KUNS-2018"),
    ("acm_class", SetACMClassification, "D.2.4"),
    ("msc_class", SetMSCClassification, "43A15"),
])
def test_optional_metadata_produces_an_event_when_supplied(field_name,
                                                           event_class, value):
    events = _events(**{field_name: value})
    assert any(isinstance(e, event_class) for e in events)


def test_no_events_for_optional_fields_left_empty():
    events = _events()
    for event_class in (SetComments, SetJournalReference, SetDOI,
                        SetReportNumber, SetACMClassification,
                        SetMSCClassification):
        assert not any(isinstance(e, event_class) for e in events)


def test_license_name_falls_back_to_the_uri():
    assert license_name_for("http://example.org/unknown-license") == \
        "http://example.org/unknown-license"


def test_known_license_gets_a_label():
    assert license_name_for(LICENSE) != LICENSE


# ------------------------------------------------------------------- uploads


@pytest.fixture
def store():
    return InMemoryDepositStore(counter=1)


def test_a_zip_becomes_an_unpacking_archive_upload(store):
    """The manual recommends bundling TeX sources as a zip."""
    store.save("10030146", "vtex", "application/zip", b"PK\x03\x04")
    events = upload_events(_metadata(), store, creator=CREATOR, client=CLIENT)
    assert _types(events) == [UploadArchive]
    assert events[0].file.filename == "10030146.zip"


def test_loose_files_become_a_single_upload_files_event(store):
    """A PDF or figure is added as-is, not unpacked (submit_sword.md:317)."""
    store.save("10030146", "vtex", "application/pdf", b"%PDF")
    store.save("10030147", "vtex", "image/png", b"\x89PNG")
    events = upload_events(_metadata(media_ids=["10030146", "10030147"]),
                           store, creator=CREATOR, client=CLIENT)

    assert _types(events) == [UploadFiles]
    assert [f.filename for f in events[0].files] == \
        ["10030146.pdf", "10030147.png"]


def test_a_zip_and_loose_files_together(store):
    store.save("10030146", "vtex", "application/zip", b"PK\x03\x04")
    store.save("10030147", "vtex", "application/pdf", b"%PDF")
    events = upload_events(_metadata(media_ids=["10030146", "10030147"]),
                           store, creator=CREATOR, client=CLIENT)
    assert _types(events) == [UploadArchive, UploadFiles]


def test_uploaded_stream_carries_the_deposited_bytes(store):
    store.save("10030146", "vtex", "application/pdf", b"%PDF-1.4")
    events = upload_events(_metadata(), store, creator=CREATOR, client=CLIENT)
    assert events[0].files[0].stream.read() == b"%PDF-1.4"


def test_a_vanished_deposit_is_an_internal_error(store):
    """parse_wrapper already proved it existed, so this means it was reaped."""
    with pytest.raises(RuntimeError, match="vanished"):
        upload_events(_metadata(), store, creator=CREATOR, client=CLIENT)


# ------------------------------------------------------------------- tracking


def test_record_tracking_tolerates_a_missing_submission_row(sword_db):
    """The tracking row is still written; only the reverse link is skipped."""
    import arxiv.db.models as models
    from arxiv.db import Session

    from submit_ce.sword.ingest import record_tracking

    record_tracking(Session, sword_id=10030146, submission_id=999999)

    tracking = Session.query(models.Tracking).filter_by(sword_id=10030146).one()
    assert tracking.paper_id == "submit/999999"
