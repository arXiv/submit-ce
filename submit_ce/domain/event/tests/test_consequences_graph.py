"""Static guarantee that the event-consequence graph terminates.

Each :class:`.Event` subclass declares, in ``CONSEQUENCE_TYPES``, the set of
event types it may emit from :meth:`.Event.consequences`. Those declarations
form a directed graph over event *types*. If that graph is acyclic, every
runtime consequence chain is a finite path through it, so the save loop that
processes consequences is guaranteed to terminate.

These tests enforce that invariant at CI time -- strictly stronger than a
runtime recursion-depth cap.
"""

# Importing the package forces registration of every Event subclass so that
# ``_get_subclasses(Event)`` sees them all.
import submit_ce.domain.event  # noqa: F401
from submit_ce.domain.event.base import Event, _get_subclasses


def _all_event_classes():
    """All production Event classes.

    Test modules may define throwaway Event subclasses (see
    ``test_detector_catches_a_self_cycle``). Pydantic's model machinery keeps a
    strong reference to every subclass, so such a class lingers in
    ``Event.__subclasses__()`` for the whole process and cannot be reliably
    cleaned up. The production invariant only concerns production events, so we
    exclude anything defined under a ``tests`` package.
    """
    classes = [Event] + _get_subclasses(Event)
    return [c for c in classes if "tests" not in c.__module__.split(".")]


def find_cycle(adjacency):
    """Return a cycle (list of nodes) in the directed graph, or None.

    ``adjacency`` maps a node to its set of successor nodes. A node referenced
    only as a successor (a leaf) is treated as having no outgoing edges.
    """
    WHITE, GREY, BLACK = 0, 1, 2
    color = {node: WHITE for node in adjacency}

    def visit(node, path):
        color[node] = GREY
        for nxt in adjacency.get(node, ()):
            if color.get(nxt) == GREY:
                return path + [node, nxt]
            if color.get(nxt, WHITE) == WHITE:
                found = visit(nxt, path + [node])
                if found:
                    return found
        color[node] = BLACK
        return None

    for node in adjacency:
        if color[node] == WHITE:
            found = visit(node, [])
            if found:
                return found
    return None


def test_declared_consequence_types_are_events():
    """Every declared consequence type is an Event subclass."""
    for cls in _all_event_classes():
        for dep in cls.CONSEQUENCE_TYPES:
            assert isinstance(dep, type) and issubclass(dep, Event), \
                f"{cls.__name__}.CONSEQUENCE_TYPES contains non-Event {dep!r}"


def test_consequence_graph_is_acyclic():
    """The real graph of (event type -> possible consequence types) is acyclic."""
    adjacency = {cls: set(cls.CONSEQUENCE_TYPES) for cls in _all_event_classes()}
    cycle = find_cycle(adjacency)
    assert cycle is None, \
        "Consequence cycle detected: " + " -> ".join(c.__name__ for c in cycle)


def test_detector_catches_a_self_cycle():
    """Sanity check that find_cycle actually fires on a cyclic graph.

    Defines a throwaway Event subclass that lists itself as a consequence -- a
    one-node cycle the detector must catch. This class lives under a ``tests``
    package, so ``_all_event_classes`` excludes it from the real acyclicity
    test even though pydantic keeps it alive in ``Event.__subclasses__()``.
    """
    class Bogus(Event):
        NAME = "bogus self-referencing event"

    # Can't reference Bogus inside its own body; wire the self-edge after.
    Bogus.CONSEQUENCE_TYPES = frozenset({Bogus})

    cycle = find_cycle({Bogus: set(Bogus.CONSEQUENCE_TYPES)})
    assert cycle is not None, "find_cycle failed to detect a self-cycle"
    assert Bogus in cycle
