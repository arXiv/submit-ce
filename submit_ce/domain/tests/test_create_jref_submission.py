"""Unit tests for `CreateJrefSubmission` and `Document.seed_submission`."""
import pytest

from submit_ce.domain.agent import HttpClient, PublicUser
from submit_ce.domain.document import Document, DocMetadata
from submit_ce.domain.event import CreateJrefSubmission
from submit_ce.domain.exceptions import InvalidEvent
from submit_ce.domain.submission import Submission, SubmissionType

PAPER_ID = '2101.00001'
LICENSE = 'http://arxiv.org/licenses/nonexclusive-distrib/1.0/'


@pytest.fixture
def creator():
    return PublicUser(user_id='42', name='Bob Paulson', email='bob@example.com')


@pytest.fixture
def document():
    """An announced paper at version 2, with no citation data yet."""
    return Document(
        paper_id=PAPER_ID,
        document_id=7,
        latest_version=2,
        metadata=[
            DocMetadata(version=1, title='Old title', is_current=False),
            DocMetadata(version=2, title='A paper about things',
                        abstract='the abstract',
                        authors='Bob Paulson (Fight Club)',
                        comments='9 pages', license=LICENSE,
                        msc_class='11F03', source_size=59392,
                        source_format='tex', is_current=True),
        ])


def test_seed_submission_uses_current_version(creator, document):
    """The seed reflects the current announced version, not the first."""
    seed = document.seed_submission(creator)

    assert seed.status == Submission.ANNOUNCED
    assert seed.is_announced
    assert seed.arxiv_id == PAPER_ID
    assert seed.version == 2
    assert seed.metadata.title == 'A paper about things'
    assert seed.metadata.authors_display == 'Bob Paulson (Fight Club)'
    assert seed.metadata.comments == '9 pages'
    assert seed.metadata.msc_class == '11F03'
    assert seed.license.uri == LICENSE


def test_seed_submission_omits_source_and_moderation_state(creator, document):
    """Source fields are not copied, matching legacy `fields_for_submission`.

    The oversize and format auto-holds are no-ops on a jref precisely because
    these are absent.
    """
    seed = document.seed_submission(creator)

    assert seed.source_format is None
    assert seed.uncompressed_size == 0
    assert seed.is_oversize is False
    assert seed.holds == {}
    assert seed.waivers == {}
    assert seed.flags == {}
    assert seed.proposals == {}
    assert seed.user_requests == {}


def test_seed_submission_with_no_metadata_rows(creator):
    """A paper with no arXiv_metadata rows still yields a usable seed."""
    seed = Document(paper_id=PAPER_ID, document_id=7,
                    latest_version=3).seed_submission(creator)

    assert seed.version == 3
    assert seed.metadata.title is None
    assert seed.license is None


def test_project_makes_a_jref(creator, document):
    """The announced seed becomes a new, unsubmitted jref submission."""
    seed = document.seed_submission(creator)
    event = CreateJrefSubmission(
        creator=creator, client=HttpClient(remote_addr='10.0.0.1'),
        paper_id=PAPER_ID, journal_ref='Phys. Rev. D 100, 1 (2019)',
        doi='10.1000/182', report_num='CERN-PH-EP/2999-018')

    after = event.apply(seed)

    assert after.submission_type is SubmissionType.JOURNAL_REFERENCE
    assert after.status == Submission.WORKING
    assert after.submitted is None
    assert after.submission_id is None      # assigned when the row is created
    assert after.arxiv_id == PAPER_ID
    assert after.creator == creator
    assert after.owner == creator

    assert after.metadata.journal_ref == 'Phys. Rev. D 100, 1 (2019)'
    assert after.metadata.doi == '10.1000/182'
    assert after.metadata.report_num == 'CERN-PH-EP/2999-018'
    # Seeded metadata survives.
    assert after.metadata.title == 'A paper about things'
    assert after.metadata.msc_class == '11F03'


def test_project_does_not_increment_version(creator, document):
    """A jref annotates the current version; it does not make a new one."""
    seed = document.seed_submission(creator)
    event = CreateJrefSubmission(creator=creator, paper_id=PAPER_ID,
                                 doi='10.1000/182')

    after = event.apply(seed)

    assert after.version == seed.version == 2


def test_project_leaves_unset_fields_alone(creator, document):
    """An empty value does not clear metadata seeded from the paper."""
    document.current_metadata.journal_ref = 'existing journal ref 1999'
    seed = document.seed_submission(creator)
    event = CreateJrefSubmission(creator=creator, paper_id=PAPER_ID,
                                 doi='10.1000/182')

    after = event.apply(seed)

    assert after.metadata.doi == '10.1000/182'
    assert after.metadata.journal_ref == 'existing journal ref 1999'


def test_requires_an_announced_paper(creator):
    """A jref cannot be made against something not yet announced."""
    working = Submission(creator=creator, owner=creator)
    event = CreateJrefSubmission(creator=creator, paper_id=PAPER_ID,
                                 doi='10.1000/182')

    with pytest.raises(InvalidEvent, match='announced'):
        event.apply(working)


def test_requires_at_least_one_value(creator, document):
    """There is nothing to record if all three fields are empty."""
    seed = document.seed_submission(creator)
    event = CreateJrefSubmission(creator=creator, paper_id=PAPER_ID)

    with pytest.raises(InvalidEvent, match='journal reference, DOI or'):
        event.apply(seed)


def test_rejects_a_bad_doi(creator, document):
    """Field validation matches the individual `Set*` events."""
    seed = document.seed_submission(creator)
    event = CreateJrefSubmission(creator=creator, paper_id=PAPER_ID,
                                 doi='not a doi at all')

    with pytest.raises(InvalidEvent):
        event.apply(seed)


def test_cleans_up_values(creator):
    """Values get the same light cleanup as the individual `Set*` events."""
    event = CreateJrefSubmission(
        creator=creator, paper_id=PAPER_ID, doi='  10.1000/182  ',
        journal_ref='PHYSICAL REVIEW LETTERS 100, 1 (2019)',
        report_num='  CERN-PH-EP/2999-018  ')

    assert event.doi == '10.1000/182'
    assert event.journal_ref == 'Physical Review Letters 100, 1 (2019)'
    assert event.report_num == 'CERN-PH-EP/2999-018'
