"""Defines submission stages and workflows supported by this UI."""

from typing import Optional, Dict

from arxiv.base import logging
from submit_ce.ui.domain import Submission
from dataclasses import field, dataclass
from . import WorkflowDefinition, Stage


logger = logging.getLogger(__file__)


@dataclass
class WorkflowProcessor:
    """Class to handle a submission moving through a WorkflowDefinition.

    The seen methods is_seen and mark_seen are handled with a Dict. This class
    doesn't handle loading or saving that data.
    """
    workflow: WorkflowDefinition
    submission: Submission
    seen: Dict[str, bool] = field(default_factory=dict)

    def is_complete(self) -> bool:
        """Determine whether this workflow is complete."""
        return bool(self.submission.is_finalized)

    def next_stage(self, stage: Optional[Stage]) -> Optional[Stage]:
        """Get the stage after the one in the parameter."""
        return self.workflow.next_stage(stage)
    
    def can_proceed_to(self, stage: Optional[Stage]) -> bool:
        """Determine whether the user can proceed to a stage."""
        if stage is None:
            return True

        must_be_done = self.workflow.order if stage == self.workflow.confirmation \
            else self.workflow.iter_prior(stage)
        done = list([(stage, self.is_done(stage)) for stage in must_be_done])
        logger.debug(f'in can_proceed_to() done list is {done}')
        return all(map(lambda x: x[1], done))

    def current_stage(self) -> Optional[Stage]:
        """Get the first stage in the workflow that is not done."""
        for stage in self.workflow.order:
            if not self.is_done(stage):
                return stage
        return None

    def _seen_key(self, stage: Stage) -> str:
        return f"{self.workflow.name}---" +\
            f"{stage.__class__.__name__}---{stage.label}---"

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
        """
        Evaluate whether a stage is sufficiently addressed for this workflow.
        This considers whether the stage is complete (if required), and whether
        the stage has been seen (if it must be seen).
        """
        if stage is None:
            return True

        return ((not stage.must_see or self.is_seen(stage))
                and
                (not stage.required or stage.is_complete(self.submission)))

    def index(self, stage):
        return self.workflow.index(stage)

