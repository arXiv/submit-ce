"""Test to trigger index string bug in __init__.py"""
from submit_ce.ui.workflow import WorkflowDefinition
from submit_ce.ui.workflow.stages import Stage

class X(Stage):
    label = "X"
    endpoint = "x"
    def is_complete(self, sub, events): return True
    def incomplete(self, sub, events): return []

class Y(Stage):
    label = "Y"
    endpoint = "y"
    def is_complete(self, sub, events): return True
    def incomplete(self, sub, events): return []

def test_index_by_string():
    wf = WorkflowDefinition("WF", order=[X(), Y()], confirmation=Y())
    assert wf.index("Y") == 1
