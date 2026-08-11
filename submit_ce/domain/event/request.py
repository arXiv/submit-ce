"""Commands/events related to user requests."""

from typing import Optional, List, ClassVar
from dataclasses import field

from pydantic import ConfigDict

from . import validators
from .base import Event
from ..submission import Submission, WithdrawalRequest, UserRequest
from ..exceptions import InvalidEvent


class ApproveRequest(Event):
    """Approve a user request."""

    NAME = "approve user request"
    NAMED = "user request approved"

    request_id: Optional[str] = field(default=None)

    # def __hash__(self) -> int:
    #     """Use event ID as object hash."""
    #     return hash(self.event_id)
    #
    # def __eq__(self, other: object) -> bool:
    #     """Compare this event to another event."""
    #     if not isinstance(other, Event):
    #         return NotImplemented
    #     return hash(self) == hash(other)

    def validate_pre_lock(self, submission: Submission) -> None:
        if self.request_id not in submission.user_requests:
            raise InvalidEvent(self, "No such request")

    def project(self, submission: Submission) -> Submission:
        assert self.request_id is not None
        submission.user_requests[self.request_id].status = UserRequest.APPROVED
        return submission


class RejectRequest(Event):
    NAME = "reject user request"
    NAMED = "user request rejected"

    request_id: Optional[str] = field(default=None)

    # def __hash__(self) -> int:
    #     """Use event ID as object hash."""
    #     return hash(self.event_id)
    #
    # def __eq__(self, other: object) -> bool:
    #     """Compare this event to another event."""
    #     if not isinstance(other, Event):
    #         return NotImplemented
    #     return hash(self) == hash(other)

    def validate_pre_lock(self, submission: Submission) -> None:
        if self.request_id not in submission.user_requests:
            raise InvalidEvent(self, "No such request")

    def project(self, submission: Submission) -> Submission:
        assert self.request_id is not None
        submission.user_requests[self.request_id].status = UserRequest.REJECTED
        return submission


class CancelRequest(Event):
    NAME = "cancel user request"
    NAMED = "user request cancelled"

    request_id: Optional[str] = field(default=None)

    # def __hash__(self) -> int:
    #     """Use event ID as object hash."""
    #     return hash(self.event_id)

    # def __eq__(self, other: object) -> bool:
    #     """Compare this event to another event."""
    #     if not isinstance(other, Event):
    #         return NotImplemented
    #     return hash(self) == hash(other)

    def validate_pre_lock(self, submission: Submission) -> None:
        if self.request_id not in submission.user_requests:
            raise InvalidEvent(self, "No such request")

    def project(self, submission: Submission) -> Submission:
        assert self.request_id is not None
        submission.user_requests[self.request_id].status = \
            UserRequest.CANCELLED
        return submission


class ApplyRequest(Event):
    NAME = "apply user request"
    NAMED = "user request applied"

    request_id: Optional[str] = field(default=None)

    # def __hash__(self) -> int:
    #     """Use event ID as object hash."""
    #     return hash(self.event_id)

    # def __eq__(self, other: object) -> bool:
    #     """Compare this event to another event."""
    #     if not isinstance(other, Event):
    #         return NotImplemented
    #     return hash(self) == hash(other)

    def validate_pre_lock(self, submission: Submission) -> None:
        if self.request_id not in submission.user_requests:
            raise InvalidEvent(self, "No such request")

    def project(self, submission: Submission) -> Submission:
        assert self.request_id is not None
        user_request = submission.user_requests[self.request_id]
        if hasattr(user_request, 'apply'):
            submission = user_request.apply(submission)
        user_request.status = UserRequest.APPLIED
        submission.user_requests[self.request_id] = user_request
        return submission


class RequestCrossList(Event):
    """Deprecated no-op shim; a cross-list is now its own submission.

    Cross-listing used to be modelled as a *request* recorded on the announced
    submission's event stream. It is now a submission of its own, created by
    :class:`.CreateCrossSubmission` and edited with :class:`.AddCrossCategory` /
    :class:`.RemoveCrossCategory`, matching legacy ``type='cross'``.

    This class survives only so that ``RequestCrossList`` rows already persisted
    deserialize and replay: without a matching class
    :meth:`.models.DBEvent.to_event` raises ``Unknown event type`` and the whole
    submission fails to load. Same reasoning, and same shape, as
    :class:`.event.legacy._LegacyUploadPackageEvent`. Projection is a pure no-op:
    a legacy cross row is surfaced by the classic loaders
    (:func:`.db.to_document`, :mod:`.patch`), not by replaying this event.

    Do not emit new instances of this event.
    """

    NAME = "request cross-list classification (deprecated no-op)"
    NAMED = "cross-list classification requested"

    model_config = ConfigDict(extra="ignore")  # tolerate old payload fields

    categories: List[str] = field(default_factory=list)

    def validate_pre_lock(self, submission: Submission) -> None:
        """No-op: deprecated event, nothing to validate."""
        return None

    def project(self, submission: Submission) -> Submission:
        """No-op: deprecated event, leaves the submission unchanged."""
        return submission


class RequestWithdrawal(Event):
    """Request that a paper be withdrawn."""

    NAME = "request withdrawal"
    NAMED = "withdrawal requested"

    reason: str = field(default_factory=str)

    MAX_LENGTH: ClassVar[int]= 400

    # def __hash__(self) -> int:
    #     """Use event ID as object hash."""
    #     return hash(self.event_id)

    # def __eq__(self, other: object) -> bool:
    #     """Compare this event to another event."""
    #     if not isinstance(other, Event):
    #         return NotImplemented
    #     return hash(self) == hash(other)

    def validate_pre_lock(self, submission: Submission) -> None:
        """Make sure that a reason was provided."""
        validators.no_active_requests(self, submission)
        if not self.reason:
            raise InvalidEvent(self, "Provide a reason for the withdrawal")
        if len(self.reason) > self.MAX_LENGTH:
            raise InvalidEvent(self, "Reason must be 400 characters or less")
        if not submission.is_announced:
            raise InvalidEvent(self, "Submission must already be announced")

    def project(self, submission: Submission) -> Submission:
        """Update the submission status and withdrawal reason."""
        assert self.created is not None
        req_id = WithdrawalRequest.generate_request_id(submission)
        user_request = WithdrawalRequest(
            request_id=req_id,
            creator=self.creator,
            created=self.created,
            updated=self.created,
            status=WithdrawalRequest.PENDING,
            reason_for_withdrawal=self.reason
        )
        submission.user_requests[req_id] = user_request
        return submission
