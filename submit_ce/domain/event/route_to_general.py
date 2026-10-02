"""Event that routes a flagged submitter's new submission to a general category.

A port of legacy ``route_to_gen`` (``arXiv::Schema::Result::Submission``), emitted
as a consequence of :class:`.FinalizeSubmission`. Which submitters are routed is
decided by :meth:`.SubmitApi.routes_to_general_category`. SUBMISSION-39.
"""

from typing import Optional, TYPE_CHECKING

from ..agent import System
from ..meta import Classification
from ..submission import Submission
from .base import EventWithSideEffect

if TYPE_CHECKING:
    from submit_ce.api.submit import SubmitApi


def general_category(primary: str) -> Optional[str]:
    """Where legacy routes a submission with this primary; None if it does not."""
    archive = primary.split('.')[0]
    if archive in ('cs', 'q-bio', 'q-fin', 'stat'):
        return None
    return {'math': 'math.GM', 'test': 'test.mtrl-sci'}.get(archive, 'physics.gen-ph')


class RouteToGeneralCategory(EventWithSideEffect):
    """Replace the submission's categories with its general category.

    Only when the submitter is routed; legacy drops the secondaries too. It is an
    `EventWithSideEffect` only because `execute` is the hook given the `SubmitApi`.
    It checks the submission's submitter, not this event's `System` creator. A
    failed lookup fails the finalize; legacy proceeds unrouted (``Suspect.pm:41-46``).
    """

    NAME = "route to general category"
    NAMED = "routed to general category"

    category: Optional[str] = None
    """The general category, set by :meth:`execute` when the submitter is routed."""

    def validate_pre_lock(self, submission: Submission) -> None:
        """No precondition; this is a consequence of a validated finalize."""
        pass

    def execute(self, api: 'SubmitApi', submission: Submission) -> None:
        """Look up whether the submitter is routed."""
        creator = submission.creator
        if not isinstance(creator, System) \
                and api.routes_to_general_category(creator.user_id, creator.email):
            self.category = general_category(submission.primary_category)

    def project(self, submission: Submission) -> Submission:
        """Set the general category as the only one."""
        if self.category:
            submission.primary_classification = Classification(category=self.category)
            submission.secondary_classification = []
        return submission
