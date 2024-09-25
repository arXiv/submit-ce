"""Defines submission stages and workflows supported by this UI."""

from typing import Iterable, Optional, List, Iterator, Union

from dataclasses import dataclass, field

from . import stages
from .stages import Stage


@dataclass
class WorkflowDefinition:
    name: str
    order: List[Stage] = field(default_factory=list)
    confirmation: Stage = None

    def __iter__(self) -> Iterator[Stage]:
        """Iterate over stages in this workflow."""
        for stage in self.order:
            yield stage

    def iter_prior(self, stage: Stage) -> Iterable[Stage]:
        """Iterate over stages in this workflow up to a particular stage."""
        for prior_stage in self.order:
            if prior_stage == stage:
                return
            yield prior_stage

    def next_stage(self, stage: Optional[Stage]) -> Optional[Stage]:
        """Get the next stage."""
        if stage is None:
            return None
        idx = self.order.index(stage)
        if idx + 1 >= len(self.order):
            return None
        return self.order[idx + 1]

    def previous_stage(self, stage: Optional[Stage]) -> Optional[Stage]:
        """Get the previous stage."""
        if stage is None:
            return None
        idx = self.order.index(stage)
        if idx == 0:
            return None
        return self.order[idx - 1]

    def stage_from_endpoint(self, endpoint: str) -> Stage:
        """Get the :class:`.Stage` for an endpoint."""
        for stage in self.order:
            if stage.endpoint == endpoint:
                return stage
            raise ValueError(f'No stage for endpoint: {endpoint}')
        return self.order[0]  # mypy

    def index(self, stage: Union[type, Stage, str]) -> int:
        if stage in self.order:
            return self.order.index(stage)
        if isinstance(stage, type) and issubclass(stage, Stage):
            for idx, st in enumerate(self.order):
                if issubclass(st.__class__, stage):
                    return idx
            raise ValueError(f"{stage} not In workflow")

        if isinstance(stage, str):  # it could be classname, stage label
            for idx, wstg in self.order:
                if(wstg.label == stage
                   or wstg.__class__.__name__ == stage):
                    return idx

        raise ValueError(f"Should be subclass of Stage, classname or stage"
                         f"instance. Cannot call with {stage} of type "
                         f"{type(stage)}")

    def __getitem__(self, query: Union[type, Stage, str, int, slice])\
        -> Union[Optional[Stage], List[Stage]]:
        if isinstance(query, slice):
            return self.order.__getitem__(query)
        else:
            return self.get_stage(query)

    def get_stage(self, query: Union[type, Stage, str, int])\
        -> Optional[Stage]:
        """Get the stage object from this workflow for Class, class name,
        stage label, endpoint or index in order """
        if query is None:
            return None
        if isinstance(query, type):
            if issubclass(query, Stage):
                stages = [st for st in self.order if issubclass(
                    st.__class__, query)]
                if len(stages) > 0:
                    return stages[0]
                else:
                    return None
            else:
                raise ValueError("Cannot call get_stage with non-Stage class")
        if isinstance(query, int):
            if query >= len(self.order) or query < 0:
                return None
            else:
                return self.order[query]

        if isinstance(query, str):
            # it could be classname, stage label or stage endpoint
            for stage in self.order:
                if(stage.label == query
                        or stage.__class__.__name__ == query
                        or stage.endpoint == query):
                    return stage
            return None
        if query in self.order:
            return self[self.order.index(query)]
        raise ValueError("query should be Stage class or class name or "
                         f"endpoint or lable str or int. Not {type(query)}")


SubmissionWorkflow = WorkflowDefinition(
    'SubmissionWorkflow',
    [stages.VerifyUser(),
     stages.Authorship(),
     stages.License(),
     stages.Policy(),
     stages.Classification(),
     stages.CrossList(required=False, must_see=True),
     stages.FileUpload(),
     stages.Process(),
     stages.Metadata(),
     stages.OptionalMetadata(required=False, must_see=True),
     stages.FinalPreview()
     ],
    stages.Confirm()
)
"""Workflow for new submissions."""

ReplacementWorkflow = WorkflowDefinition(
    'ReplacementWorkflow',
    [stages.VerifyUser(must_see=True),
     stages.Authorship(must_see=True),
     stages.License(must_see=True),
     stages.Policy(must_see=True),
     stages.FileUpload(must_see=True),
     stages.Process(must_see=True),
     stages.Metadata(must_see=True),
     stages.OptionalMetadata(required=False, must_see=True),
     stages.FinalPreview(must_see=True)
     ],
    stages.Confirm()
)
"""Workflow for replacements."""
