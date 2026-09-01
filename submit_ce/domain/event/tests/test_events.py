"""Tests for :class:`.Event` instances in :mod:`arxiv.submission.domain.event`."""

from datetime import datetime
from unittest import TestCase, mock

from arxiv.taxonomy.definitions import CATEGORIES, CATEGORIES_ACTIVE
from pytz import UTC

from submit_ce.domain import agent, event, meta, submission
from submit_ce.domain.exceptions import InvalidEvent
from submit_ce.domain.uploads import SourceFormat

user = agent.PublicUser(
    name="Bob Somebody",
    user_id = "12345",
    email='uuser@cornell.edu',            
    endorsements=['astro-ph.GA', 'astro-ph.CO']
)

class TestWithdrawalSubmission(TestCase):
    """Test :class:`event.RequestWithdrawal`."""

    def setUp(self):
        """Initialize auxiliary data for test cases."""
        self.user = user
        self.submission = submission.Submission(
            submission_id="1",
            status=submission.Submission.ANNOUNCED,
            creator=self.user,
            owner=self.user,
            created=datetime.now(UTC),
            source_format=SourceFormat('pdf'),
            uncompressed_size=594930,
            primary_classification=meta.Classification('astro-ph.GA'),
            secondary_classification=[meta.Classification('astro-ph.CO')],
            license=meta.License(uri='http://free', name='free'),
            arxiv_id='1901.001234',
            version=1,
            submitter_contact_verified=True,
            submitter_is_author=True,
            submitter_accepts_policy=True,
            submitter_confirmed_preview=True,
            metadata=submission.SubmissionMetadata(
                title='the best title',
                abstract='very abstract',
                authors_display='J K Jones, F W Englund',
                doi='10.1000/182',
                comments='These are the comments'
            )
        )

    def test_request_withdrawal(self):
        """Request that a paper be withdrawn."""
        e = event.RequestWithdrawal(creator=self.user,
                                    created=datetime.now(UTC),
                                    reason="no good")
        e.validate_pre_lock(self.submission)
        replacement = e.apply(self.submission)
        self.assertEqual(replacement.arxiv_id, self.submission.arxiv_id)
        self.assertEqual(replacement.version, self.submission.version)
        self.assertEqual(replacement.status,
                         submission.Submission.ANNOUNCED)
        self.assertTrue(replacement.has_active_requests)
        self.assertTrue(self.submission.is_announced)
        self.assertTrue(replacement.is_announced)

    def test_request_without_a_reason(self):
        """A reason is required."""
        e = event.RequestWithdrawal(creator=self.user)
        with self.assertRaises(event.InvalidEvent):
            e.validate_pre_lock(self.submission)

    def test_request_without_announced_submission(self):
        """The submission must already be announced."""
        e = event.RequestWithdrawal(creator=self.user, reason="no good")
        with self.assertRaises(event.InvalidEvent):
            e.validate_pre_lock(mock.MagicMock(announced=False))


class TestReplacementSubmission(TestCase):
    """Test :class:`event.CreateSubmission` with a replacement."""

    def setUp(self):
        """Initialize auxiliary data for test cases."""
        self.user = user
        self.submission = submission.Submission(
            submission_id="1",
            status=submission.Submission.ANNOUNCED,
            creator=self.user,
            owner=self.user,
            created=datetime.now(UTC),
            source_format=SourceFormat('pdf'),
            uncompressed_size=594930,
            primary_classification=meta.Classification('astro-ph.GA'),
            secondary_classification=[meta.Classification('astro-ph.CO')],
            license=meta.License(uri='http://free', name='free'),
            arxiv_id='1901.001234',
            version=1,
            submitter_contact_verified=True,
            submitter_is_author=True,
            submitter_accepts_policy=True,
            submitter_confirmed_preview=True,
            metadata=submission.SubmissionMetadata(
                title='the best title',
                abstract='very abstract',
                authors_display='J K Jones, F W Englund',
                doi='10.1000/182',
                comments='These are the comments'
            )
        )

    def test_create_submission_replacement(self):
        """A replacement is a new submission based on an old submission."""
        e = event.CreateSubmissionVersion(creator=self.user)
        replacement = e.apply(self.submission)
        self.assertEqual(replacement.arxiv_id, self.submission.arxiv_id)
        self.assertEqual(replacement.version, self.submission.version + 1)
        self.assertEqual(replacement.status, submission.Submission.WORKING)
        self.assertTrue(self.submission.is_announced)
        self.assertFalse(replacement.is_announced)

        self.assertIsNone(replacement.source_format)

        # The user is asked to reaffirm these points.
        self.assertFalse(replacement.submitter_contact_verified)
        self.assertFalse(replacement.submitter_accepts_policy)
        self.assertFalse(replacement.submitter_confirmed_preview)
        self.assertFalse(replacement.submitter_contact_verified)

        # These should all stay the same.
        self.assertEqual(replacement.metadata.title,
                         self.submission.metadata.title)
        self.assertEqual(replacement.metadata.abstract,
                         self.submission.metadata.abstract)
        self.assertEqual(replacement.metadata.authors,
                         self.submission.metadata.authors)
        self.assertEqual(replacement.metadata.authors_display,
                         self.submission.metadata.authors_display)
        self.assertEqual(replacement.metadata.msc_class,
                         self.submission.metadata.msc_class)
        self.assertEqual(replacement.metadata.acm_class,
                         self.submission.metadata.acm_class)
        self.assertEqual(replacement.metadata.doi,
                         self.submission.metadata.doi)
        self.assertEqual(replacement.metadata.journal_ref,
                         self.submission.metadata.journal_ref)


class TestDOIorJREFAfterAnnounce(TestCase):
    """Test :class:`event.SetDOI` or :class:`event.SetJournalReference`."""

    def setUp(self):
        """Initialize auxiliary data for test cases."""
        self.user = user
        self.submission = submission.Submission(
            submission_id="1",
            status=submission.Submission.ANNOUNCED,
            creator=self.user,
            owner=self.user,
            created=datetime.now(UTC),
            source_format=SourceFormat('pdf'),
            uncompressed_size=594930,
            primary_classification=meta.Classification('astro-ph.GA'),
            secondary_classification=[meta.Classification('astro-ph.CO')],
            license=meta.License(uri='http://free', name='free'),
            arxiv_id='1901.001234',
            version=1,
            submitter_contact_verified=True,
            submitter_is_author=True,
            submitter_accepts_policy=True,
            submitter_confirmed_preview=True,
            metadata=submission.SubmissionMetadata(
                title='the best title',
                abstract='very abstract',
                authors_display='J K Jones, F W Englund',
                doi='10.1000/182',
                comments='These are the comments'
            )
        )

    def test_create_submission_jref(self):
        """A JREF is just like a replacement, but different."""
        e = event.SetDOI(creator=self.user, doi='10.1000/182')
        after = e.apply(self.submission)
        self.assertEqual(after.arxiv_id, self.submission.arxiv_id)
        self.assertEqual(after.version, self.submission.version)
        self.assertEqual(after.status, submission.Submission.ANNOUNCED)
        self.assertTrue(self.submission.is_announced)
        self.assertTrue(after.is_announced)

        self.assertIsNotNone(after.submission_id)
        self.assertEqual(self.submission.submission_id, after.submission_id)

        # The user is NOT asked to reaffirm these points.
        self.assertTrue(after.submitter_contact_verified)
        self.assertTrue(after.submitter_accepts_policy)
        self.assertTrue(after.submitter_confirmed_preview)
        self.assertTrue(after.submitter_contact_verified)

        # These should all stay the same.
        self.assertEqual(after.metadata.title,
                         self.submission.metadata.title)
        self.assertEqual(after.metadata.abstract,
                         self.submission.metadata.abstract)
        self.assertEqual(after.metadata.authors,
                         self.submission.metadata.authors)
        self.assertEqual(after.metadata.authors_display,
                         self.submission.metadata.authors_display)
        self.assertEqual(after.metadata.msc_class,
                         self.submission.metadata.msc_class)
        self.assertEqual(after.metadata.acm_class,
                         self.submission.metadata.acm_class)
        self.assertEqual(after.metadata.doi,
                         self.submission.metadata.doi)
        self.assertEqual(after.metadata.journal_ref,
                         self.submission.metadata.journal_ref)



class TestSetPrimaryClassification(TestCase):
    """Test :class:`event.SetPrimaryClassification`."""

    def setUp(self):
        """Initialize auxiliary data for test cases."""
        self.user = user
        self.submission = submission.Submission(
            submission_id="1",
            creator=self.user,
            owner=self.user,
            created=datetime.now(UTC)
        )

    def test_set_primary_with_nonsense(self):
        """Category is not from the arXiv taxonomy."""
        e = event.SetPrimaryClassification(
            creator=self.user,
            submission_id="1",
            category="nonsense"
        )
        with self.assertRaises(InvalidEvent):
            e.validate_pre_lock(self.submission)    # "Event should not be valid".

    def test_set_primary_inactive(self):
        """Category is not from the arXiv taxonomy."""
        e = event.SetPrimaryClassification(
            creator=self.user,
            submission_id="1",
            category="chao-dyn"
        )
        with self.assertRaises(InvalidEvent):
            e.validate_pre_lock(self.submission)    # "Event should not be valid".

    def test_set_primary_with_valid_category(self):
        """Category is from the arXiv taxonomy."""
        for category in CATEGORIES.keys():
            e = event.SetPrimaryClassification(
                creator=self.user,
                submission_id="1",
                category=category
            )
            if category in self.user.endorsements:
                try:
                    e.validate_pre_lock(self.submission)
                except InvalidEvent as e:
                    self.fail("Event should be valid")
            else:
                with self.assertRaises(InvalidEvent):
                    e.validate_pre_lock(self.submission)

    def test_set_primary_already_secondary(self):
        """Category is already set as a secondary."""
        classification = submission.Classification('cond-mat.dis-nn')
        self.submission.secondary_classification.append(classification)
        e = event.SetPrimaryClassification(
            creator=self.user,
            submission_id="1",
            category='cond-mat.dis-nn'
        )
        with self.assertRaises(InvalidEvent):
            e.validate_pre_lock(self.submission)    # "Event should not be valid".


class TestAddSecondaryClassification(TestCase):
    """Test :class:`event.AddSecondaryClassification`."""

    def setUp(self):
        """Initialize auxiliary data for test cases."""
        self.user = user
        self.submission = submission.Submission(
            submission_id="1",
            creator=self.user,
            owner=self.user,
            created=datetime.now(UTC),
            secondary_classification=[]
        )

    def test_add_secondary_with_nonsense(self):
        """Category is not from the arXiv taxonomy."""
        e = event.AddSecondaryClassification(
            creator=self.user,
            submission_id="1",
            category="nonsense"
        )
        with self.assertRaises(InvalidEvent):
            e.validate_pre_lock(self.submission)    # "Event should not be valid".

    def test_add_secondary_inactive(self):
        """Category is inactive."""
        e = event.AddSecondaryClassification(
            creator=self.user,
            submission_id="1",
            category="bayes-an"
        )
        with self.assertRaises(InvalidEvent):
            e.validate_pre_lock(self.submission)

    def test_add_secondary_with_valid_category(self):
        """Category is from the arXiv taxonomy."""
        for category in CATEGORIES_ACTIVE.keys():
            e = event.AddSecondaryClassification(
                creator=self.user,
                submission_id="1",
                category=category
            )
            try:
                e.validate_pre_lock(self.submission)
            except InvalidEvent:
                if category != 'physics.gen-ph':
                    self.fail("Event should be valid")

    def test_add_secondary_already_present(self):
        """Category is already present on the submission."""
        self.submission.secondary_classification.append(
            submission.Classification('cond-mat.dis-nn')
        )
        e = event.AddSecondaryClassification(
            creator=self.user,
            submission_id="1",
            category='cond-mat.dis-nn'
        )
        with self.assertRaises(InvalidEvent):
            e.validate_pre_lock(self.submission)    # "Event should not be valid".

    def test_add_secondary_already_primary(self):
        """Category is already set as primary."""
        classification = submission.Classification('cond-mat.dis-nn')
        self.submission.primary_classification = classification

        e = event.AddSecondaryClassification(
            creator=self.user,
            submission_id="1",
            category='cond-mat.dis-nn'
        )
        with self.assertRaises(InvalidEvent):
            e.validate_pre_lock(self.submission)    # "Event should not be valid".

    def test_add_general_secondary(self):
        """Category is more general than the existing categories."""
        classification = submission.Classification('physics.optics')
        self.submission.primary_classification = classification

        e = event.AddSecondaryClassification(
            creator=self.user,
            submission_id="1",
            category='physics.gen-ph'
        )
        with self.assertRaises(InvalidEvent):
            e.validate_pre_lock(self.submission)    # "Event should not be valid".

        classification = submission.Classification('cond-mat.quant-gas')
        self.submission.primary_classification = classification
            
        self.submission.secondary_classification.append(
            submission.Classification('physics.optics'))
        e = event.AddSecondaryClassification(
            creator=self.user,
            submission_id="1",
            category='physics.gen-ph'
        )
        with self.assertRaises(InvalidEvent):
            e.validate_pre_lock(self.submission)    # "Event should not be valid".

    def test_add_specific_secondary(self):
        """Category is more specific than existing general category."""
        classification = submission.Classification('physics.gen-ph')
        self.submission.primary_classification = classification

        e = event.AddSecondaryClassification(
            creator=self.user,
            submission_id="1",
            category='physics.optics'
        )
        with self.assertRaises(InvalidEvent):
            e.validate_pre_lock(self.submission)    # "Event should not be valid".

        classification = submission.Classification('astro-ph.SR')
        self.submission.primary_classification = classification

        self.submission.secondary_classification.append(
            submission.Classification('physics.gen-ph'))
        e = event.AddSecondaryClassification(
            creator=self.user,
            submission_id="1",
            category='physics.optics'
        )
        with self.assertRaises(InvalidEvent):
            e.validate_pre_lock(self.submission)    # "Event should not be valid".

    def test_add_max_secondaries(self):
        """Test max secondaries."""
        self.submission.secondary_classification.append(
            submission.Classification('cond-mat.dis-nn'))
        self.submission.secondary_classification.append(
            submission.Classification('cond-mat.mes-hall'))
        self.submission.secondary_classification.append(
            submission.Classification('cond-mat.mtrl-sci'))

        e1 = event.AddSecondaryClassification(
            creator=self.user,
            submission_id="1",
            category='cond-mat.quant-gas'
        )
        e1.validate_pre_lock(self.submission)
        self.submission.secondary_classification.append(
            submission.Classification('cond-mat.quant-gas'))

        e2 = event.AddSecondaryClassification(
            creator=self.user,
            submission_id="1",
            category='cond-mat.str-el'
        )

        self.assertEqual(len(self.submission.secondary_classification), 4)
        with self.assertRaises(InvalidEvent):
            e2.validate_pre_lock(self.submission)    # "Event should not be valid".


class TestRemoveSecondaryClassification(TestCase):
    """Test :class:`event.RemoveSecondaryClassification`."""

    def setUp(self):
        """Initialize auxiliary data for test cases."""
        self.user = user
        self.submission = submission.Submission(
            submission_id="1",
            creator=self.user,
            owner=self.user,
            created=datetime.now(UTC),
            secondary_classification=[]
        )

    def test_add_secondary_with_nonsense(self):
        """Category is not from the arXiv taxonomy."""
        e = event.RemoveSecondaryClassification(
            creator=self.user,
            submission_id="1",
            category="nonsense"
        )
        with self.assertRaises(InvalidEvent):
            e.validate_pre_lock(self.submission)    # "Event should not be valid".

    def test_remove_secondary_with_valid_category(self):
        """Category is from the arXiv taxonomy."""
        classification = submission.Classification('cond-mat.dis-nn')
        self.submission.secondary_classification.append(classification)
        e = event.RemoveSecondaryClassification(
            creator=self.user,
            submission_id="1",
            category='cond-mat.dis-nn'
        )
        try:
            e.validate_pre_lock(self.submission)
        except InvalidEvent as e:
            self.fail("Event should be valid")

    def test_remove_secondary_not_present(self):
        """Category is not present."""
        e = event.RemoveSecondaryClassification(
            creator=self.user,
            submission_id="1",
            category='cond-mat.dis-nn'
        )
        with self.assertRaises(InvalidEvent):
            e.validate_pre_lock(self.submission)    # "Event should not be valid".


class TestSetAuthors(TestCase):
    """Test :class:`event.SetAuthors`."""

    def setUp(self):
        """Initialize auxiliary data for test cases."""
        self.user = user
        self.submission = submission.Submission(
            submission_id="1",
            creator=self.user,
            owner=self.user,
            created=datetime.now(UTC)
        )

    def test_empty_value(self):
        """Authors is set to an empty string (no authors provided)."""
        e = event.SetAuthors(creator=self.user)
        with self.assertRaises(InvalidEvent):
            e.validate_pre_lock(self.submission)

    def test_canonical_authors_provided(self):
        """Data includes canonical author display string."""
        e = event.SetAuthors(creator=self.user,
                                submission_id="1",
                                authors=[submission.Author()],
                                authors_display="Foo authors")
        try:
            e.validate_pre_lock(self.submission)
        except Exception as e:
            self.fail(str(e), "Data should be valid")
        s = e.project(self.submission)
        self.assertEqual(s.metadata.authors_display, e.authors_display,
                         "Authors string should be updated")

    def test_canonical_authors_not_provided(self):
        """Data does not include canonical author display string."""
        e = event.SetAuthors(
            creator=self.user,
            submission_id="1",
            authors=[
                submission.Author(
                    forename="Bob",
                    surname="Paulson",
                    affiliation="FSU"
                )
            ])
        self.assertEqual(e.authors_display, "Bob Paulson (FSU)",
                         "Display string should be generated automagically")

        try:
            e.validate_pre_lock(self.submission)
        except Exception as e:
            self.fail(str(e), "Data should be valid")
        s = e.project(self.submission)
        self.assertEqual(s.metadata.authors_display, e.authors_display,
                         "Authors string should be updated")


class TestSetTitle(TestCase):
    """Tests for :class:`.event.SetTitle`."""

    def setUp(self):
        """Initialize auxiliary data for test cases."""
        self.user = user
        self.submission = submission.Submission(
            submission_id="1",
            creator=self.user,
            owner=self.user,
            created=datetime.now(UTC)
        )

    def test_empty_value(self):
        """Title is set to an empty string."""
        e = event.SetTitle(creator=self.user, title='')
        with self.assertRaises(InvalidEvent):
            e.validate_pre_lock(self.submission)


class TestSetAbstract(TestCase):
    """Tests for :class:`.event.SetAbstract`."""

    def setUp(self):
        """Initialize auxiliary data for test cases."""
        self.user = user
        self.submission = submission.Submission(
            submission_id="1",
            creator=self.user,
            owner=self.user,
            created=datetime.now(UTC)
        )

    def test_empty_value(self):
        """Abstract is set to an empty string."""
        e = event.SetAbstract(creator=self.user, abstract='')
        with self.assertRaises(InvalidEvent):
            e.validate_pre_lock(self.submission)


class TestSetDOI(TestCase):
    """Tests for :class:`.event.SetDOI`."""

    def setUp(self):
        """Initialize auxiliary data for test cases."""
        self.user = user
        self.submission = submission.Submission(
            submission_id="1",
            creator=self.user,
            owner=self.user,
            created=datetime.now(UTC)
        )

    def test_empty_doi(self):
        """DOI is set to an empty string."""
        doi = ""
        e = event.SetDOI(creator=self.user, doi=doi)
        try:
            e.validate_pre_lock(self.submission)
        except InvalidEvent as e:
            self.fail('Failed to handle valid DOI: %s' % e)


class TestSetReportNumber(TestCase):
    """Tests for :class:`.event.SetReportNumber`."""

    def setUp(self):
        """Initialize auxiliary data for test cases."""
        self.user = user
        self.submission = submission.Submission(
            submission_id="1",
            creator=self.user,
            owner=self.user,
            created=datetime.now(UTC)
        )

    def test_empty_report_num(self):
        """Report num is set to an empty string (blank is OK)."""
        e = event.SetReportNumber(creator=self.user, report_num="")
        try:
            e.validate_pre_lock(self.submission)
        except InvalidEvent as e:
            self.fail('Failed to handle empty report_num: %s' % e)


class TestSetJournalReference(TestCase):
    """Tests for :class:`.event.SetJournalReference`."""

    def setUp(self):
        """Initialize auxiliary data for test cases."""
        self.user = user
        self.submission = submission.Submission(
            submission_id="1",
            creator=self.user,
            owner=self.user,
            created=datetime.now(UTC)
        )

    def test_empty_journal_ref(self):
        """JREF is set to an empty string (blank is OK)."""
        e = event.SetJournalReference(creator=self.user, journal_ref="")
        try:
            e.validate_pre_lock(self.submission)
        except InvalidEvent as e:
            self.fail('Failed to handle empty jref: %s' % e)


class TestSetACMClassification(TestCase):
    """Tests for :class:`.event.SetACMClassification`."""

    def setUp(self):
        """Initialize auxiliary data for test cases."""
        self.user = user
        self.submission = submission.Submission(
            submission_id="1",
            creator=self.user,
            owner=self.user,
            created=datetime.now(UTC)
        )

    def test_empty_acm_class(self):
        """ACM classification is set to an empty string (blank is OK)."""
        e = event.SetACMClassification(creator=self.user, acm_class="")
        try:
            e.validate_pre_lock(self.submission)
        except InvalidEvent as e:
            self.fail('Failed to handle empty acm_class: %s' % e)


class TestSetMSCClassification(TestCase):
    """Tests for :class:`.event.SetMSCClassification`."""

    def setUp(self):
        """Initialize auxiliary data for test cases."""
        self.user = user
        self.submission = submission.Submission(
            submission_id="1",
            creator=self.user,
            owner=self.user,
            created=datetime.now(UTC)
        )

    def test_empty_msc_class(self):
        """MSC classification is set to an empty string (blank is OK)."""
        e = event.SetMSCClassification(creator=self.user, msc_class="")
        try:
            e.validate_pre_lock(self.submission)
        except InvalidEvent as e:
            self.fail('Failed to handle empty msc_class: %s' % e)


class TestSetComments(TestCase):
    """Tests for :class:`.event.SetComments`."""

    def setUp(self):
        """Initialize auxiliary data for test cases."""
        self.user = user
        self.submission = submission.Submission(
            submission_id="1",
            creator=self.user,
            owner=self.user,
            created=datetime.now(UTC)
        )

    def test_empty_value(self):
        """Comment is set to an empty string."""
        e = event.SetComments(creator=self.user, comments='')
        try:
            e.validate_pre_lock(self.submission)
        except InvalidEvent as e:
            self.fail('Failed to handle empty comments')
