"""Unit tests for `CreateJrefSubmission` and `Document.seed_submission`."""
import pytest

from submit_ce.domain.agent import HttpClient, PublicUser
from submit_ce.domain.document import Document, DocMetadata
from submit_ce.domain.event import CreateJrefSubmission
from submit_ce.domain.exceptions import InvalidEvent
from submit_ce.domain.meta import Classification, License
from submit_ce.domain.submission import Submission, SubmissionMetadata, \
    SubmissionType

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
    """A paper with nothing to seed from still yields a usable seed."""
    seed = Document(paper_id=PAPER_ID, document_id=7,
                    latest_version=3).seed_submission(creator)

    assert seed.version == 3
    assert seed.metadata.title is None
    assert seed.license is None


def _announced_submission(creator, **overrides):
    """An announced submission row, as `to_submission` would build it."""
    fields = dict(
        creator=creator, owner=creator, arxiv_id=PAPER_ID, version=2,
        status=Submission.ANNOUNCED, license=License(uri=LICENSE),
        primary_classification=Classification(category='astro-ph.GA'),
        secondary_classification=[Classification(category='astro-ph.CO')],
        metadata=SubmissionMetadata(
            title='From the submission row', abstract='row abstract',
            authors_display='Bob Paulson', comments='7 pages',
            msc_class='11F03'))
    fields.update(overrides)
    return Submission(**fields)


def test_seed_falls_back_to_the_announced_submission(creator):
    """With no arXiv_metadata row, the announced submission is the source.

    That table is written by the legacy publish pipeline, not by this system,
    so a paper announced here has no row in it. Seeding must not produce a
    submission with an empty title and abstract.
    """
    document = Document(paper_id=PAPER_ID, document_id=7, latest_version=2,
                        submissions=[_announced_submission(creator)])
    assert document.current_metadata is None    # nothing in arXiv_metadata

    seed = document.seed_submission(creator)

    assert seed.version == 2
    assert seed.metadata.title == 'From the submission row'
    assert seed.metadata.abstract == 'row abstract'
    assert seed.metadata.authors_display == 'Bob Paulson'
    assert seed.metadata.comments == '7 pages'
    assert seed.metadata.msc_class == '11F03'
    assert seed.license.uri == LICENSE


def test_seed_falls_back_for_classifications(creator):
    """With no arXiv_document_category rows, categories come from the row."""
    document = Document(paper_id=PAPER_ID, document_id=7, latest_version=2,
                        submissions=[_announced_submission(creator)])
    assert document.primary_classification is None

    seed = document.seed_submission(creator)

    assert seed.primary_classification.category == 'astro-ph.GA'
    assert [c.category for c in seed.secondary_classification] \
        == ['astro-ph.CO']


def test_document_rows_win_over_the_fallback(creator):
    """When the paper does have announced metadata, that is preferred."""
    document = Document(
        paper_id=PAPER_ID, document_id=7, latest_version=2,
        primary_classification=Classification(category='hep-th'),
        metadata=[DocMetadata(version=2, title='From arXiv_metadata',
                              is_current=True)],
        submissions=[_announced_submission(creator)])

    seed = document.seed_submission(creator)

    assert seed.metadata.title == 'From arXiv_metadata'
    assert seed.primary_classification.category == 'hep-th'


def test_seed_ignores_non_announced_submissions(creator):
    """An in-progress submission is not a source for the announced state."""
    working = _announced_submission(
        creator, status=Submission.WORKING, version=3,
        metadata=SubmissionMetadata(title='unannounced draft'))
    document = Document(paper_id=PAPER_ID, document_id=7, latest_version=2,
                        submissions=[_announced_submission(creator), working])

    seed = document.seed_submission(creator)

    assert seed.metadata.title == 'From the submission row'
    assert seed.version == 2


def test_project_makes_a_jref(creator, document):
    """The announced seed becomes a new, unsubmitted jref submission."""
    seed = document.seed_submission(creator)
    event = CreateJrefSubmission(
        creator=creator, client=HttpClient(remote_addr='10.0.0.1'),
        paper_id=PAPER_ID)

    after = event.apply(seed)

    assert after.submission_type is SubmissionType.JOURNAL_REFERENCE
    assert after.status == Submission.WORKING
    assert after.submitted is None
    assert after.submission_id is None      # assigned when the row is created
    assert after.arxiv_id == PAPER_ID
    assert after.creator == creator
    assert after.owner == creator

    assert after.metadata.journal_ref == None
    assert after.metadata.doi == None
    assert after.metadata.report_num == None
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
    event = CreateJrefSubmission(creator=creator, paper_id=PAPER_ID)
    after = event.apply(seed)
    assert after.metadata.doi == None
    assert after.metadata.journal_ref == 'existing journal ref 1999'


def test_requires_an_announced_paper(creator):
    """A jref cannot be made against something not yet announced."""
    working = Submission(creator=creator, owner=creator)
    event = CreateJrefSubmission(creator=creator, paper_id=PAPER_ID,
                                 doi='10.1000/182')

    with pytest.raises(InvalidEvent, match='announced'):
        event.apply(working)
