"""Unit tests for `FinalizeJrefSubmission`."""
from datetime import datetime

import pytest
from pytz import UTC

from submit_ce.domain.agent import HttpClient, PublicUser, System
from submit_ce.domain.document import Document, DocMetadata
from submit_ce.domain.event import CreateJrefSubmission, \
    EmailSubmitterFinalizeMsg, FinalizeJrefSubmission
from submit_ce.domain.exceptions import InvalidEvent
from submit_ce.domain.meta import Classification
from submit_ce.domain.submission import Submission

PAPER_ID = '2101.00001'
LICENSE = 'http://arxiv.org/licenses/nonexclusive-distrib/1.0/'
JOURNAL_REF = 'Phys. Rev. D 100, 1 (2019)'
CREATED = datetime(2026, 7, 30, 18, 30, tzinfo=UTC)


@pytest.fixture
def creator():
    return PublicUser(user_id='42', name='Bob Paulson', email='bob@example.com')


@pytest.fixture
def document():
    """An announced paper, ready to have a journal reference added."""
    return Document(
        paper_id=PAPER_ID,
        document_id=7,
        latest_version=2,
        primary_classification=Classification(category='astro-ph.GA'),
        secondary_classification=[Classification(category='astro-ph.CO')],
        metadata=[
            DocMetadata(version=2, title='A paper about things',
                        abstract='the abstract',
                        authors='Bob Paulson (Fight Club)',
                        comments='9 pages', license=LICENSE, is_current=True),
        ])


@pytest.fixture
def jref(creator, document):
    """A working jref submission carrying a journal reference."""
    seed = document.seed_submission(creator,
                                    HttpClient(remote_addr='10.0.0.1'))
    submission = CreateJrefSubmission(
        creator=creator, paper_id=PAPER_ID, created=CREATED).apply(seed)
    submission.submission_id = '1234'
    submission.metadata.journal_ref = JOURNAL_REF
    return submission


def _event(creator, **kwargs):
    kwargs.setdefault('created', CREATED)
    return FinalizeJrefSubmission(creator=creator, **kwargs)


def test_finalize_submits_and_records_the_time(creator, jref):
    """Status becomes submitted and the submit time is recorded."""
    after = _event(creator).apply(jref)

    assert after.status == Submission.SUBMITTED
    assert after.is_finalized
    assert after.submitted == CREATED


def test_submit_time_is_stable_across_replays(creator, jref):
    """`project` is replayed on every read, so it must not read the clock."""
    event = _event(creator)

    first = event.apply(jref)
    second = event.apply(jref)

    assert first.submitted == second.submitted == CREATED


def test_no_file_state_is_required(creator, jref):
    """A jref changes no files, so the source and preview checks do not apply.

    The announced paper's files are what get announced; a jref is seeded
    without `source_format` and never uploads or compiles anything, so
    requiring them (as `FinalizeSubmission` does) would reject every one.
    """
    assert jref.source_format is None
    assert jref.preview is None
    assert jref.is_source_processed is False
    assert jref.submitter_confirmed_preview is False

    after = _event(creator).apply(jref)

    assert after.status == Submission.SUBMITTED


def test_no_oversize_hold(creator, jref):
    """Even a submission that claims to be oversize gets no hold.

    The flag belongs to the source package, which a jref does not touch; a
    hold here would also misroute the submitter's email to the auto-hold
    template.
    """
    jref.is_oversize = True
    event = _event(creator)

    after = event.apply(jref)

    assert after.holds == {}
    assert [type(e) for e in event.get_consequences(after)] \
        == [EmailSubmitterFinalizeMsg]


def test_general_primary_with_secondaries_is_allowed(creator, document):
    """Inherited categories must not block the update (SUBMISSION-158).

    Unlike a new submission, the submitter did not choose these and has no way
    to change them, so a grandfathered-in combination has to go through.
    """
    document.primary_classification = Classification(category='math.GM')
    seed = document.seed_submission(creator)
    jref = CreateJrefSubmission(creator=creator, paper_id=PAPER_ID,
                                created=CREATED).apply(seed)
    jref.metadata.doi = '10.1000/182'
    assert jref.secondary_classification    # the inherited cross-list

    after = _event(creator).apply(jref)

    assert after.status == Submission.SUBMITTED


def test_emails_the_submitter_and_no_one_else(creator, jref):
    """The submitter's confirmation is the only mail a jref generates.

    A journal reference never reaches moderation, so there is no moderator
    notification.
    """
    event = _event(creator)
    after = event.apply(jref)

    consequences = event.get_consequences(after)

    assert len(consequences) == 1
    email = consequences[0]
    assert isinstance(email, EmailSubmitterFinalizeMsg)
    assert email.email_to == creator
    assert email.submission_id == '1234'
    assert isinstance(email.creator, System)
    assert email.cause == event.event_id


def test_rejects_a_non_jref_submission(creator, document):
    """`FinalizeSubmission` is the event for every other type."""
    working = Submission(creator=creator, owner=creator,
                         primary_classification=Classification(
                             category='astro-ph.GA'))

    with pytest.raises(InvalidEvent, match='Not a journal reference'):
        _event(creator).apply(working)


def test_rejects_an_already_finalized_jref(creator, jref):
    """A jref is submitted once; a second finalize is a bug or a double post."""
    submitted = _event(creator).apply(jref)

    with pytest.raises(InvalidEvent, match='already finalized'):
        _event(creator).apply(submitted)


def test_rejects_an_announced_submission(creator, jref):
    """An announced jref is past submitting; `is_finalized` covers it."""
    jref.status = Submission.ANNOUNCED

    with pytest.raises(InvalidEvent, match='already finalized'):
        _event(creator).apply(jref)


def test_rejects_a_deleted_jref(creator, jref):
    """A deleted jref cannot be submitted."""
    jref.status = Submission.DELETED

    with pytest.raises(InvalidEvent, match='must be active'):
        _event(creator).apply(jref)


def test_requires_citation_data(creator, jref):
    """A jref with nothing to record has nothing to announce."""
    jref.metadata.journal_ref = None

    with pytest.raises(InvalidEvent,
                       match='journal reference, a DOI or a report number'):
        _event(creator).apply(jref)


@pytest.mark.parametrize('field,value', [
    ('journal_ref', JOURNAL_REF),
    ('doi', '10.1000/182'),
    ('report_num', 'CERN-PH-EP/2999-018'),
])
def test_any_one_citation_value_is_enough(creator, jref, field, value):
    """Any of the three values a journal reference can carry will do."""
    jref.metadata.journal_ref = None
    setattr(jref.metadata, field, value)

    assert _event(creator).apply(jref).status == Submission.SUBMITTED


def test_requires_inherited_metadata(creator, jref):
    """Seeding from the announced paper must actually have produced metadata."""
    jref.metadata.title = None

    with pytest.raises(InvalidEvent, match='Missing title'):
        _event(creator).apply(jref)


def test_requires_a_primary_classification(creator, jref):
    """A jref inherits the paper's primary; without one it cannot be routed.

    Legacy treats this as a safety net -- it puts the submission on hold rather
    than announcing something uncategorized. There is no hold in this path, so
    it is rejected instead.
    """
    jref.primary_classification = None

    with pytest.raises(InvalidEvent, match='Missing primary_classification'):
        _event(creator).apply(jref)


def test_policy_and_contact_flags_are_not_required(creator, jref):
    """The jref form asks neither, so they are never set on a jref."""
    assert jref.submitter_accepts_policy is None
    assert jref.submitter_contact_verified is False

    assert _event(creator).apply(jref).status == Submission.SUBMITTED
