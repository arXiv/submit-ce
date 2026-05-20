"""Test to trigger index string bug in __init__.py"""
from submit_ce.ui.workflow import WorkflowDefinition
from submit_ce.ui.workflow.stages import Stage

class X(Stage):
    label = "X"
    endpoint = "x"
    def is_complete(self, sub): return True
    def incomplete(self, sub): return []

class Y(Stage):
    label = "Y"
    endpoint = "y"
    def is_complete(self, sub): return True
    def incomplete(self, sub): return []

def test_index_by_string():
    wf = WorkflowDefinition("WF", order=[X(), Y()], confirmation=Y())
    assert wf.index("Y") == 1
