"""Defines submission stages and workflows supported by this UI."""

from typing import List, Optional, Dict, Tuple
import logging

from submit_ce.domain import Submission, Event
from dataclasses import field, dataclass
from . import WorkflowDefinition, Stage


logger = logging.getLogger(__name__)


@dataclass
class WorkflowProcessor:
    """Class to handle a submission moving through a WorkflowDefinition.

    The seen methods is_seen and mark_seen are handled with a Dict. This class
    doesn't handle loading or saving that data.
    """
    workflow: WorkflowDefinition
    submission: Submission
    events: List[Event] = field(default_factory=list)
    seen: Dict[str, bool] = field(default_factory=dict)

    def is_complete(self) -> bool:
        """Determine whether this workflow is complete."""
        return bool(self.submission.is_finalized)

    def next_stage(self, stage: Optional[Stage]) -> Optional[Stage]:
        """Get the stage after the one in the parameter."""
        return self.workflow.next_stage(stage)
    
    def can_proceed_to(self, stage: Optional[Stage]) -> bool:
        """Determine whether the user can proceed to a stage."""
        return stage is None or not self.blocked(stage)

    def blocked(self, stage: Stage) -> List[Tuple[str,str]]:
        """If blocked, returns list of blocking conditions, if not blocked
        returns empty list."""
        use_confirmation = stage == self.workflow.confirmation
        if use_confirmation:
            must_be_done = self.workflow.order
        else:
            must_be_done = self.workflow.iter_prior(stage)
        must_be_done = list(must_be_done)

        not_dones = [(stage.__class__.__name__, self.not_done(stage)) for stage in must_be_done]
        not_dones = [(name, prob) for name, prob in not_dones if prob]
        logger.debug("Stages not done list: %s", not_dones)
        # if not_doens is empty, the user can_proceed_to stage
        return not_dones

    def current_stage(self) -> Optional[Stage]:
        """Get the first stage in the workflow that is not done."""
        for stage in self.workflow.order:
            if not self.is_done(stage):
                return stage
        return None

    def _seen_key(self, stage: Stage) -> str:
        return f"{self.workflow.name}---" +\
            f"{stage.__class__.__name__}---{stage.label}---"

    # TODO !!! MARK SEEN DOES NOT RECORD ANYTHING !!!
    def mark_seen(self, stage: Optional[Stage]) -> None:
        """Mark a stage as seen by the user."""
        if stage is not None:
            self.seen[self._seen_key(stage)] = True

    def is_seen(self, stage: Optional[Stage]) -> bool:
        """Determine whether the user has seen this stage."""
        if stage is None:
            return True
        return self.seen.get(self._seen_key(stage), False)

    def is_done(self, stage: Optional[Stage]) -> bool:
        """Evaluate if stage is sufficiently addressed for this workflow.

        This considers whether the stage is complete (if required), and whether
        the stage has been seen (if it must be seen).
        """
        if stage is None:
            return True

        return ((not stage.must_see or self.is_seen(stage))
                and
                (not stage.required or stage.is_complete(self.submission, self.events)))

    def not_done(self, stage: Optional[Stage]) -> list[str]:
        """Returns list of conditons causing stage to be not done.

        Retrun empty list if stage is done."""
        if stage is None:
            return []
        not_dones=[]
        if stage.must_see and not self.is_seen(stage):
            not_dones.append(f"{stage.__class__.__name__} must be seen")
        incomplete_fns = stage.incomplete(self.submission, self.events)
        if stage.required and incomplete_fns:
            not_dones.extend(incomplete_fns)
        return not_dones

    def index(self, stage):
        return self.workflow.index(stage)
