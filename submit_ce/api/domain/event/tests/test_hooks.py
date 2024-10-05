"""Test callback hook functionality on :class:`Event`."""

from unittest import TestCase, mock
from dataclasses import dataclass
from ..base import Event
from ...agent import System, Agent


class TestCommitEvent(TestCase):
    """Tests for :func:`Event.bind` and :class:`Event.commit`."""

    def test_commit_event(self):
        """Test a simple commit hook."""
        class ChildEvent(Event):
            def _should_apply_callbacks(self):
                return True

        class OtherChildEvent(Event):
            def _should_apply_callbacks(self):
                return True

        callback = mock.MagicMock(return_value=[], __name__='test')
        ChildEvent.bind(lambda *a: True)(callback)     # Register callback.

        save = mock.MagicMock(
            return_value=(mock.MagicMock(), mock.MagicMock())
        )
        agent = Agent(native_id="fake", name="fake", username="fake", email="fake")
        event = ChildEvent(creator=agent)
        event.after = mock.MagicMock()
        OtherChildEvent(creator=agent)
        event.commit(save)
        self.assertEqual(callback.call_count, 1,
                         "Callback is only executed on the class to which it"
                         " is bound")

    def test_callback_inheritance(self):
        """Callback is inherited by subclasses."""
        class ParentEvent(Event):
            def _should_apply_callbacks(self):
                return True

        class ChildEvent(ParentEvent):
            def _should_apply_callbacks(self):
                return True

        callback = mock.MagicMock(return_value=[], __name__='test')
        ParentEvent.bind(lambda *a: True)(callback)     # Register callback.

        save = mock.MagicMock(
            return_value=(mock.MagicMock(), mock.MagicMock())
        )
        event = ChildEvent(creator=System(native_id='system'))
        event.after = mock.MagicMock()
        event.commit(save)
        self.assertEqual(callback.call_count, 1,
                         "Callback bound to parent class is called when child"
                         " is committed")
