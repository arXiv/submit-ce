"""Unit tests for `FinalizeCrossSubmission`."""
from datetime import datetime

import pytest
from pytz import UTC

from submit_ce.domain.agent import HttpClient, PublicUser, System
from submit_ce.domain.document import Document, DocMetadata
from submit_ce.domain.event import AddCrossCategory, CreateCrossSubmission, \
    EmailModeratorsFinalizeMsg, EmailSubmitterFinalizeMsg, \
    FinalizeCrossSubmission
from submit_ce.domain.exceptions import InvalidEvent
from submit_ce.domain.meta import Classification
from submit_ce.domain.submission import Hold, Submission, SubmissionType

PAPER_ID = '2101.00001'
LICENSE = 'http://arxiv.org/licenses/nonexclusive-distrib/1.0/'
CREATED = datetime(2026, 7, 31, 18, 30, tzinfo=UTC)


@pytest.fixture
def creator():
    return PublicUser(user_id='42', name='Bob Paulson', email='bob@example.com')


@pytest.fixture
def document():
    """An announced paper, ready to be cross-listed."""
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
def cross(creator, document):
    """A working cross submission with one category added."""
    seed = document.seed_submission(creator,
                                    HttpClient(remote_addr='10.0.0.1'))
    submission = CreateCrossSubmission(
        creator=creator, paper_id=PAPER_ID, created=CREATED).apply(seed)
    submission.submission_id = '1234'
    return AddCrossCategory(creator=creator, category='cs.DL',
                            created=CREATED).apply(submission)


def _event(creator, **kwargs):
    kwargs.setdefault('created', CREATED)
    return FinalizeCrossSubmission(creator=creator, **kwargs)


def test_finalize_submits_and_records_the_time(creator, cross):
    """Status becomes submitted and the submit time is recorded."""
    after = _event(creator).apply(cross)

    assert after.status == Submission.SUBMITTED
    assert after.is_finalized
    assert after.submitted == CREATED


def test_submit_time_is_stable_across_replays(creator, cross):
    """`project` is replayed on every read, so it must not read the clock."""
    event = _event(creator)

    first = event.project(cross)
    second = _event(creator).project(cross)

    assert first.submitted == second.submitted == CREATED


def test_requires_a_category_to_add(creator, document):
    """Legacy: "Please add categories before submitting"."""
    seed = document.seed_submission(creator)
    cross_with_nothing_added = CreateCrossSubmission(
        creator=creator, paper_id=PAPER_ID, created=CREATED).apply(seed)
    assert cross_with_nothing_added.secondary_categories == ['astro-ph.CO']

    with pytest.raises(InvalidEvent, match='add categories'):
        _event(creator).apply(cross_with_nothing_added)


def test_rejects_a_non_cross_submission(creator, cross):
    """This event finalizes a cross-list, nothing else."""
    cross.submission_type = SubmissionType.REPLACEMENT

    with pytest.raises(InvalidEvent, match='Not a cross-list submission'):
        _event(creator).apply(cross)


def test_rejects_an_already_finalized_submission(creator, cross):
    submitted = _event(creator).apply(cross)

    with pytest.raises(InvalidEvent, match='already finalized'):
        _event(creator).apply(submitted)


def test_rejects_an_inactive_submission(creator, cross):
    cross.status = Submission.DELETED

    with pytest.raises(InvalidEvent, match='must be active'):
        _event(creator).apply(cross)


@pytest.mark.parametrize('field', ['title', 'abstract', 'authors_display'])
def test_requires_the_inherited_metadata(creator, cross, field):
    """The announced metadata a cross rides on must have survived."""
    setattr(cross.metadata, field, None)

    with pytest.raises(InvalidEvent, match=f'Missing {field}'):
        _event(creator).apply(cross)


def test_requires_a_primary_classification(creator, cross):
    cross.primary_classification = None

    with pytest.raises(InvalidEvent, match='Missing primary_classification'):
        _event(creator).apply(cross)


def test_notifies_the_submitter_and_the_moderators(creator, cross):
    """A cross generates both emails; unlike a jref it does reach moderation."""
    event = _event(creator)
    after = event.apply(cross)

    consequences = event.get_consequences(after)

    assert [type(e) for e in consequences] == [EmailSubmitterFinalizeMsg,
                                               EmailModeratorsFinalizeMsg]
    submitter_msg, mod_msg = consequences
    assert submitter_msg.email_to == creator
    assert submitter_msg.submission_id == '1234'
    assert mod_msg.submission_id == '1234'
    assert all(isinstance(e.creator, System) for e in consequences)


def test_declared_consequence_types_are_honored(creator, cross):
    """`get_consequences` enforces `CONSEQUENCE_TYPES`, so this must not raise."""
    event = _event(creator)
    after = event.apply(cross)

    for consequence in event.get_consequences(after):
        assert type(consequence) in FinalizeCrossSubmission.CONSEQUENCE_TYPES


def test_an_auto_held_cross_skips_the_moderator_email(creator, cross):
    """A held submission is not sent to moderators until it is fixed.

    A cross should never be auto-held (it changes no files), but the guard is
    shared with the other finalize events, so it is asserted here too.
    """
    cross.is_oversize = True
    cross.holds['h1'] = Hold(event_id='h1', creator=creator,
                             hold_type=Hold.Type.SOURCE_OVERSIZE)
    event = _event(creator)
    after = event.apply(cross)

    consequences = event.get_consequences(after)

    assert [type(e) for e in consequences] == [EmailSubmitterFinalizeMsg]
