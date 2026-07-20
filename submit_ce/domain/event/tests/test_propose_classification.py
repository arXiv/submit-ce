"""Tests for :class:`.ProposeClassification`."""

from datetime import datetime
from unittest import TestCase

from pytz import UTC

from submit_ce.domain import event, agent, submission, meta
from submit_ce.domain.proposal import ProposalStatus
from submit_ce.domain.exceptions import InvalidEvent

user = agent.PublicUser(
    name="Bob Somebody",
    user_id="12345",
    email="uuser@cornell.edu",
    endorsements=["astro-ph.GA", "astro-ph.CO"],
)


class TestProposeClassification(TestCase):
    """Test recording a category proposal on a submission."""

    def setUp(self):
        self.user = user
        self.submission = submission.Submission(
            submission_id="1",
            status=submission.Submission.WORKING,
            creator=self.user,
            owner=self.user,
            created=datetime.now(UTC),
            primary_classification=meta.Classification("astro-ph.GA"),
        )

    def _propose(self, category="cs.AI", is_primary=True, comment="please"):
        return event.ProposeClassification(
            creator=self.user, created=datetime.now(UTC),
            category=category, is_primary=is_primary, comment=comment)

    def test_propose_primary_records_proposal(self):
        """A primary proposal is recorded as an unresolved Proposal."""
        e = self._propose(category="cs.AI", is_primary=True)
        after = e.apply(self.submission)
        self.assertEqual(len(after.proposals), 1)
        proposal = next(iter(after.proposals.values()))
        self.assertEqual(proposal.category, "cs.AI")
        self.assertTrue(proposal.is_primary)
        self.assertEqual(proposal.status, ProposalStatus.UNRESOLVED)
        self.assertTrue(proposal.is_unresolved)
        self.assertEqual(proposal.comment, "please")

    def test_propose_secondary_is_not_primary(self):
        """A cross-list proposal has ``is_primary`` False."""
        e = self._propose(category="astro-ph.CO", is_primary=False)
        after = e.apply(self.submission)
        proposal = next(iter(after.proposals.values()))
        self.assertFalse(proposal.is_primary)

    def test_proposal_does_not_change_classification(self):
        """Proposing does not alter the submission's actual categories."""
        e = self._propose(category="cs.AI", is_primary=True)
        after = e.apply(self.submission)
        self.assertEqual(after.primary_classification.category, "astro-ph.GA")

    def test_missing_category_is_invalid(self):
        e = event.ProposeClassification(creator=self.user,
                                        created=datetime.now(UTC))
        with self.assertRaises(InvalidEvent):
            e.validate_pre_lock(self.submission)

    def test_inactive_category_is_invalid(self):
        e = self._propose(category="not.a.category")
        with self.assertRaises(InvalidEvent):
            e.validate_pre_lock(self.submission)

    def test_duplicate_unresolved_proposal_is_invalid(self):
        """The same category cannot be proposed twice while unresolved."""
        first = self._propose(category="cs.AI", is_primary=True)
        after = first.apply(self.submission)
        second = self._propose(category="cs.AI", is_primary=True)
        with self.assertRaises(InvalidEvent):
            second.validate_pre_lock(after)
