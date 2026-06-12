"""Tests for user request events."""

import unittest
from datetime import datetime
from dataclasses import dataclass
from pytz import UTC

from submit_ce.domain import agent
from submit_ce.domain.event.request import (
    ApproveRequest, RejectRequest, CancelRequest, ApplyRequest,
    RequestCrossList, RequestWithdrawal
)
from submit_ce.domain.submission import (
    Submission, UserRequest, WithdrawalRequest, CrossListClassificationRequest,
    Classification
)
from submit_ce.domain.exceptions import InvalidEvent

class TestRequestEvents(unittest.TestCase):
    def setUp(self):
        self.user = agent.PublicUser(
            name="Bob Somebody",
            user_id="12345",
            email='uuser@cornell.edu'
        )
        self.submission = Submission(
            submission_id="1",
            creator=self.user,
            owner=self.user,
            created=datetime.now(UTC),
            status=Submission.WORKING
        )

    def test_approve_request(self):
        """Test ApproveRequest validation and projection."""
        # Setup: add a pending request
        request_id = "req123"
        self.submission.user_requests[request_id] = UserRequest(
            request_id=request_id,
            creator=self.user,
            created=datetime.now(UTC),
            status=UserRequest.PENDING
        )
        
        # Test valid approval
        e = ApproveRequest(creator=self.user, request_id=request_id)
        e.validate_pre_lock(self.submission)
        updated_submission = e.project(self.submission)
        self.assertEqual(updated_submission.user_requests[request_id].status, UserRequest.APPROVED)

        # Test invalid approval (non-existent request)
        e_invalid = ApproveRequest(creator=self.user, request_id="nonexistent")
        with self.assertRaises(InvalidEvent):
            e_invalid.validate_pre_lock(self.submission)

    def test_reject_request(self):
        """Test RejectRequest validation and projection."""
        # Setup: add a pending request
        request_id = "req123"
        self.submission.user_requests[request_id] = UserRequest(
            request_id=request_id,
            creator=self.user,
            created=datetime.now(UTC),
            status=UserRequest.PENDING
        )
        
        # Test valid rejection
        e = RejectRequest(creator=self.user, request_id=request_id)
        e.validate_pre_lock(self.submission)
        updated_submission = e.project(self.submission)
        self.assertEqual(updated_submission.user_requests[request_id].status, UserRequest.REJECTED)

        # Test invalid rejection (non-existent request)
        e_invalid = RejectRequest(creator=self.user, request_id="nonexistent")
        with self.assertRaises(InvalidEvent):
            e_invalid.validate_pre_lock(self.submission)

    def test_cancel_request(self):
        """Test CancelRequest validation and projection."""
        # Setup: add a pending request
        request_id = "req123"
        self.submission.user_requests[request_id] = UserRequest(
            request_id=request_id,
            creator=self.user,
            created=datetime.now(UTC),
            status=UserRequest.PENDING
        )
        
        # Test valid cancellation
        e = CancelRequest(creator=self.user, request_id=request_id)
        e.validate_pre_lock(self.submission)
        updated_submission = e.project(self.submission)
        self.assertEqual(updated_submission.user_requests[request_id].status, UserRequest.CANCELLED)

        # Test invalid cancellation (non-existent request)
        e_invalid = CancelRequest(creator=self.user, request_id="nonexistent")
        with self.assertRaises(InvalidEvent):
            e_invalid.validate_pre_lock(self.submission)

    def test_apply_request(self):
        """Test ApplyRequest validation and projection."""
        # Setup: add an approved request that has an 'apply' method
        request_id = "req123"
        # We need a subclass of UserRequest that implements apply
        @dataclass
        class MockRequest(UserRequest):
            def apply(self, sub: Submission) -> Submission:
                sub.metadata.title = "Updated Title"
                return sub

        self.submission.user_requests[request_id] = MockRequest(
            request_id=request_id,
            creator=self.user,
            created=datetime.now(UTC),
            status=UserRequest.APPROVED
        )
        
        # Test valid application
        e = ApplyRequest(creator=self.user, request_id=request_id)
        e.validate_pre_lock(self.submission)
        updated_submission = e.project(self.submission)
        self.assertEqual(updated_submission.user_requests[request_id].status, UserRequest.APPLIED)
        self.assertEqual(updated_submission.metadata.title, "Updated Title")

        # Test invalid application (non-existent request)
        e_invalid = ApplyRequest(creator=self.user, request_id="nonexistent")
        with self.assertRaises(InvalidEvent):
            e_invalid.validate_pre_lock(self.submission)

    def test_request_crosslist(self):
        """Test RequestCrossList validation and projection."""
        self.submission.status = Submission.ANNOUNCED
        self.submission.arxiv_id = "1234.5678"
        self.submission.primary_classification = Classification(category="physics.gen-ph")
        
        # Test valid crosslist request
        created = datetime.now(UTC)
        e = RequestCrossList(creator=self.user, created=created, categories=["astro-ph.GA"])
        e.validate_pre_lock(self.submission)
        updated_submission = e.project(self.submission)
        
        self.assertEqual(len(updated_submission.user_requests), 1)
        req = list(updated_submission.user_requests.values())[0]
        self.assertIsInstance(req, CrossListClassificationRequest)
        self.assertEqual(req.categories, ["astro-ph.GA"])

        # Clear requests for further validation tests
        self.submission.user_requests = {}

        # Test invalid: not announced
        self.submission.status = Submission.WORKING
        with self.assertRaises(InvalidEvent) as cm:
            e.validate_pre_lock(self.submission)
        self.assertIn("Submission must already be announced", str(cm.exception))
        self.submission.status = Submission.ANNOUNCED

        # Test invalid: already primary
        e_bad = RequestCrossList(creator=self.user, categories=["physics.gen-ph"])
        with self.assertRaises(InvalidEvent):
            e_bad.validate_pre_lock(self.submission)

    def test_request_withdrawal(self):
        """Test RequestWithdrawal validation and projection."""
        self.submission.status = Submission.ANNOUNCED
        self.submission.arxiv_id = "1234.5678"
        
        # Test valid withdrawal request
        created = datetime.now(UTC)
        e = RequestWithdrawal(creator=self.user, created=created, reason="Too many typos")
        e.validate_pre_lock(self.submission)
        updated_submission = e.project(self.submission)
        
        self.assertEqual(len(updated_submission.user_requests), 1)
        req = list(updated_submission.user_requests.values())[0]
        self.assertIsInstance(req, WithdrawalRequest)
        self.assertEqual(req.reason_for_withdrawal, "Too many typos")

        # Clear requests for further validation tests
        self.submission.user_requests = {}

        # Test invalid: no reason
        e_no_reason = RequestWithdrawal(creator=self.user, reason="")
        with self.assertRaises(InvalidEvent) as cm:
            e_no_reason.validate_pre_lock(self.submission)
        self.assertIn("Provide a reason", str(cm.exception))

        # Test invalid: reason too long
        e_long_reason = RequestWithdrawal(creator=self.user, reason="a" * 401)
        with self.assertRaises(InvalidEvent) as cm:
            e_long_reason.validate_pre_lock(self.submission)
        self.assertIn("400 characters or less", str(cm.exception))

        # Test invalid: not announced
        self.submission.status = Submission.WORKING
        e_valid_reason = RequestWithdrawal(creator=self.user, reason="valid")
        with self.assertRaises(InvalidEvent) as cm:
            e_valid_reason.validate_pre_lock(self.submission)
        self.assertIn("Submission must already be announced", str(cm.exception))
