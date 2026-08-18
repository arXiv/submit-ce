"""Unit tests for `AddCrossCategory` and `RemoveCrossCategory`.

The per-category rules are legacy's ``Secondaries::validate`` checks (see
``cross-legacy-description.md`` §3).
"""
import pytest

from submit_ce.domain.agent import PublicUser
from submit_ce.domain.event import AddCrossCategory, AddSecondaryClassification, \
    RemoveCrossCategory
from submit_ce.domain.exceptions import InvalidEvent
from submit_ce.domain.meta import Classification
from submit_ce.domain.submission import Submission, SubmissionMetadata, \
    SubmissionType

PAPER_ID = '2101.00001'


@pytest.fixture
def creator():
    return PublicUser(user_id='42', name='Bob Paulson', email='bob@example.com')


def _cross(creator, primary='astro-ph.GA', published=('astro-ph.CO',),
           added=(), version=2, status=Submission.WORKING,
           submission_type=SubmissionType.CROSS_LIST):
    """A cross submission mid-edit: inherited categories plus pending ones."""
    secondaries = [Classification(category=c, is_published=True)
                   for c in published]
    secondaries += [Classification(category=c) for c in added]
    return Submission(
        submission_id='1234',
        creator=creator, owner=creator, arxiv_id=PAPER_ID, version=version,
        status=status, submission_type=submission_type,
        primary_classification=Classification(category=primary,
                                              is_published=True),
        secondary_classification=secondaries,
        metadata=SubmissionMetadata(title='A paper about things',
                                    abstract='the abstract',
                                    authors_display='Bob Paulson'))


def test_add_records_an_unpublished_category(creator):
    """The added category is marked not-yet-announced, the rest untouched."""
    submission = _cross(creator)

    after = AddCrossCategory(creator=creator, category='cs.DL').apply(submission)

    assert after.secondary_categories == ['astro-ph.CO', 'cs.DL']
    assert after.new_cross_categories == ['cs.DL']
    assert [c.category for c in after.secondary_classification
            if c.is_published] == ['astro-ph.CO']


def test_add_rejects_a_non_cross_submission(creator):
    """These events only apply to a cross-list submission."""
    submission = _cross(creator, submission_type=SubmissionType.REPLACEMENT)

    with pytest.raises(InvalidEvent, match='Not a cross-list submission'):
        AddCrossCategory(creator=creator, category='cs.DL').apply(submission)


def test_add_rejects_a_finalized_submission(creator):
    """A submitted cross must be unfinalized before it can be edited."""
    submission = _cross(creator, status=Submission.SUBMITTED)

    with pytest.raises(InvalidEvent, match='finalized'):
        AddCrossCategory(creator=creator, category='cs.DL').apply(submission)


def test_add_requires_a_category(creator):
    with pytest.raises(InvalidEvent, match='Must have a category'):
        AddCrossCategory(creator=creator).apply(_cross(creator))


def test_add_rejects_an_inactive_category(creator):
    with pytest.raises(InvalidEvent, match='Not a valid category'):
        AddCrossCategory(creator=creator,
                         category='not.a-category').apply(_cross(creator))


def test_add_rejects_the_primary(creator):
    with pytest.raises(InvalidEvent, match='primary and a secondary'):
        AddCrossCategory(creator=creator,
                         category='astro-ph.GA').apply(_cross(creator))


def test_add_rejects_a_category_already_present(creator):
    """Whether it was inherited or added earlier in this same cross."""
    with pytest.raises(InvalidEvent, match='already set'):
        AddCrossCategory(creator=creator,
                         category='astro-ph.CO').apply(_cross(creator))

    with pytest.raises(InvalidEvent, match='already set'):
        AddCrossCategory(creator=creator, category='cs.DL').apply(
            _cross(creator, added=('cs.DL',)))


def test_add_rejects_gen_ph(creator):
    """Legacy hard-blocks `physics.gen-ph` as a cross target, even for admins."""
    with pytest.raises(InvalidEvent, match='physics.gen-ph'):
        AddCrossCategory(creator=creator,
                         category='physics.gen-ph').apply(_cross(creator))


def test_add_rejects_a_redundant_general_category(creator):
    """No general category when the archive is already represented."""
    submission = _cross(creator, primary='hep-th', published=('math.AG',))

    with pytest.raises(InvalidEvent, match='Cannot add general category'):
        AddCrossCategory(creator=creator,
                         category='math.GM').apply(submission)


def test_add_rejects_a_specific_category_under_a_general_one(creator):
    """No specific category when a general one already covers the archive."""
    submission = _cross(creator, primary='hep-th', published=('math.GM',))

    with pytest.raises(InvalidEvent, match='more spcific'):
        AddCrossCategory(creator=creator,
                         category='math.AG').apply(submission)


def test_add_rejects_any_cross_under_a_general_primary_whatever_the_version(
        creator):
    """The general-primary rule is version-independent for a cross.

    `AddSecondaryClassification` exempts ``version > 1`` -- right for a
    replacement, whose categories are all inherited and possibly grandfathered
    in, but wrong for a cross, where legacy blocks the add on the *document's*
    primary regardless of version.
    """
    submission = _cross(creator, primary='physics.gen-ph', published=(),
                        version=4)

    with pytest.raises(InvalidEvent, match='primary category'):
        AddCrossCategory(creator=creator, category='cs.DL').apply(submission)

    # The general-submission event does allow it at version > 1.
    AddSecondaryClassification(creator=creator,
                               category='cs.DL').apply(submission)


def test_add_enforces_the_four_category_limit(creator):
    """The fifth secondary is refused, aliases counting once."""
    at_limit = _cross(creator, published=('astro-ph.CO', 'cs.DL', 'math.AG',
                                          'q-bio.CB'))
    with pytest.raises(InvalidEvent, match='No more than 4'):
        AddCrossCategory(creator=creator, category='hep-th').apply(at_limit)

    # `math.MP` and `math-ph` are the same category, so this one has room.
    with_aliases = _cross(creator, published=('math.MP', 'math-ph', 'cs.DL',
                                              'q-bio.CB'))
    after = AddCrossCategory(creator=creator,
                             category='hep-th').apply(with_aliases)
    assert 'hep-th' in after.new_cross_categories


def test_remove_drops_a_pending_category(creator):
    submission = _cross(creator, added=('cs.DL', 'hep-th'))

    after = RemoveCrossCategory(creator=creator,
                                category='cs.DL').apply(submission)

    assert after.new_cross_categories == ['hep-th']
    assert after.secondary_categories == ['astro-ph.CO', 'hep-th']


def test_remove_refuses_a_published_category(creator):
    """An announced category is not the cross's to take away."""
    submission = _cross(creator, added=('cs.DL',))

    with pytest.raises(InvalidEvent, match='already announced'):
        RemoveCrossCategory(creator=creator,
                            category='astro-ph.CO').apply(submission)


def test_remove_refuses_a_category_not_on_the_submission(creator):
    with pytest.raises(InvalidEvent, match='No such category'):
        RemoveCrossCategory(creator=creator,
                            category='hep-th').apply(_cross(creator))


def test_remove_rejects_a_non_cross_submission(creator):
    submission = _cross(creator, added=('cs.DL',),
                        submission_type=SubmissionType.JOURNAL_REFERENCE)

    with pytest.raises(InvalidEvent, match='Not a cross-list submission'):
        RemoveCrossCategory(creator=creator,
                            category='cs.DL').apply(submission)


def test_remove_rejects_a_finalized_submission(creator):
    submission = _cross(creator, added=('cs.DL',), status=Submission.SUBMITTED)

    with pytest.raises(InvalidEvent, match='finalized'):
        RemoveCrossCategory(creator=creator,
                            category='cs.DL').apply(submission)
