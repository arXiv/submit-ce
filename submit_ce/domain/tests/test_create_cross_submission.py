"""Unit tests for `CreateCrossSubmission` and the published-category snapshot."""
import pytest

from submit_ce.domain.agent import HttpClient, PublicUser
from submit_ce.domain.document import Document, DocMetadata
from submit_ce.domain.event import CreateCrossSubmission
from submit_ce.domain.exceptions import InvalidEvent
from submit_ce.domain.meta import Classification
from submit_ce.domain.submission import Submission, SubmissionType

PAPER_ID = '2101.00001'


@pytest.fixture
def creator():
    return PublicUser(user_id='42', name='Bob Paulson', email='bob@example.com')


def _document(primary='astro-ph.GA', secondaries=('astro-ph.CO',), version=2):
    """An announced paper with the categories a cross starts from."""
    return Document(
        paper_id=PAPER_ID,
        document_id=7,
        latest_version=version,
        primary_classification=Classification(category=primary),
        secondary_classification=[Classification(category=c)
                                  for c in secondaries],
        metadata=[DocMetadata(version=version, title='A paper about things',
                              abstract='the abstract',
                              authors='Bob Paulson (Fight Club)',
                              is_current=True)])


def _event(creator, **kwargs):
    fields = dict(creator=creator, client=HttpClient(remote_addr='10.0.0.1'),
                  paper_id=PAPER_ID)
    fields.update(kwargs)
    return CreateCrossSubmission(**fields)


def test_seeded_categories_are_published(creator):
    """The paper's current categories are marked as already announced.

    Legacy's `make_sub_cats` copies each `arXiv_document_category` row in with
    `is_published = 1`; that snapshot is what later distinguishes an inherited
    category from a cross this submission is adding.
    """
    seed = _document().seed_submission(creator)

    assert seed.primary_classification.is_published is True
    assert all(c.is_published for c in seed.secondary_classification)
    assert seed.new_crosses == []
    assert seed.new_cross_categories == []


def test_seeding_does_not_mutate_the_document(creator):
    """The seed's categories are copies, so edits cannot reach the Document."""
    document = _document()
    seed = document.seed_submission(creator)

    seed.secondary_classification.clear()

    assert [c.category for c in document.secondary_classification] \
        == ['astro-ph.CO']
    assert document.primary_classification.is_published is False


def test_project_makes_a_cross(creator):
    """The announced seed becomes a new, unsubmitted cross submission."""
    seed = _document().seed_submission(creator)

    after = _event(creator).apply(seed)

    assert after.submission_type is SubmissionType.CROSS_LIST
    assert after.status == Submission.WORKING
    assert after.submitted is None
    assert after.submission_id is None      # assigned when the row is created
    assert after.arxiv_id == PAPER_ID
    assert after.creator == creator
    assert after.owner == creator
    # Seeded metadata and categories survive, and nothing is being added yet.
    assert after.metadata.title == 'A paper about things'
    assert after.secondary_categories == ['astro-ph.CO']
    assert after.new_cross_categories == []


def test_project_does_not_increment_version(creator):
    """A cross adds to the current version; it does not make a new one."""
    seed = _document(version=3).seed_submission(creator)

    after = _event(creator).apply(seed)

    assert after.version == seed.version == 3


def test_requires_an_announced_paper(creator):
    """A cross cannot be made against something not yet announced."""
    working = Submission(creator=creator, owner=creator)

    with pytest.raises(InvalidEvent, match='announced'):
        _event(creator).apply(working)


def test_rejects_a_general_primary(creator):
    """A paper with a general primary category is not cross-listable."""
    seed = _document(primary='physics.gen-ph',
                     secondaries=()).seed_submission(creator)

    with pytest.raises(InvalidEvent, match='general primary'):
        _event(creator).apply(seed)


def test_rejects_a_paper_already_at_the_secondary_limit(creator):
    """Four secondaries is the legacy cap, so there is no room for a cross."""
    seed = _document(secondaries=('astro-ph.CO', 'cs.DL', 'math.AG',
                                  'q-bio.CB')).seed_submission(creator)

    with pytest.raises(InvalidEvent, match='No more than 4'):
        _event(creator).apply(seed)


def test_aliases_count_once_toward_the_limit(creator):
    """`math.MP` and `math-ph` are one category, as in legacy's `minimal_list`.

    Counting them separately would refuse a cross on a paper that legacy accepts.
    """
    seed = _document(secondaries=('math.MP', 'math-ph', 'cs.DL',
                                  'math.AG')).seed_submission(creator)

    after = _event(creator).apply(seed)     # Three unique, so room for one more.

    assert after.submission_type is SubmissionType.CROSS_LIST


class _Api:
    """Stub `SubmitApi` exposing just what `validate_under_lock` reads."""

    def __init__(self, document):
        self._document = document

    def get_document(self, paper_id):
        return self._document


def test_under_lock_rejects_a_conflicting_active_submission(creator):
    """One active submission per paper, whatever its type."""
    document = _document()
    seed = document.seed_submission(creator)
    in_progress = document.seed_submission(creator)
    in_progress.status = Submission.WORKING
    in_progress.submission_type = SubmissionType.REPLACEMENT
    document.submissions = [in_progress]

    with pytest.raises(InvalidEvent, match='already has a submission'):
        _event(creator).validate_under_lock(_Api(document), seed)


def test_under_lock_allows_a_paper_with_no_active_submission(creator):
    """Nothing in progress, so the cross may be created."""
    document = _document()
    seed = document.seed_submission(creator)

    # Must not raise.
    _event(creator).validate_under_lock(_Api(document), seed)
