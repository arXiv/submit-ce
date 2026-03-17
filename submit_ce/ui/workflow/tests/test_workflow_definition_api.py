"""Test basic workflow definition and previous/current/next functions."""
import pytest
from submit_ce.ui.workflow import WorkflowDefinition
from submit_ce.ui.workflow.stages import Stage

class A(Stage):
    label = "A"
    endpoint = "ep_a"        # <-- add this
    def is_complete(self, sub): return False
    def incomplete(self, sub): return ["A incomplete"]

class B(Stage):
    label = "B"
    endpoint = "ep_b"        # <-- add this
    def is_complete(self, sub): return True
    def incomplete(self, sub): return []

class C(Stage):
    label = "C"
    endpoint = "ep_c"        # <-- add this
    def is_complete(self, sub): return True
    def incomplete(self, sub): return []

@pytest.mark.usefixtures("app")
def test_workflow_definition_core_apis():
    wf = WorkflowDefinition(
        name="WF",
        order=[A(), B(), C()],
        confirmation=C()
    )

    # __iter__
    assert [type(s).__name__ for s in wf] == ["A", "B", "C"]

    # iter_prior: yields up to but not including the target
    assert [type(s).__name__ for s in wf.iter_prior(wf.order[2])] == ["A", "B"]

    # next_stage / previous_stage (including edges)
    assert type(wf.next_stage(wf.order[0])).__name__ == "B"
    assert wf.next_stage(wf.order[-1]) is None
    assert wf.previous_stage(wf.order[0]) is None
    assert type(wf.previous_stage(wf.order[2])).__name__ == "B"

    # __getitem__ / get_stage by int
    assert type(wf[0]).__name__ == "A"
    assert wf.get_stage(10) is None  # out-of-range int

    # get_stage by class and by string (classname)
    assert type(wf.get_stage(B)).__name__ == "B"
    assert type(wf.get_stage("B")).__name__ == "B"

    # get_stage(): error when given non-Stage class
    with pytest.raises(ValueError):
        wf.get_stage(list)

    # slice returns list of Stage instances
    sl = wf[0:2]
    assert [type(s).__name__ for s in sl] == ["A", "B"]
