"""Test util.py under api/domain/event"""
import pytest
import dataclasses
import submit_ce.domain.event.util as event_util

#
# 1) dataclass() with NO kwargs: should wrap base dataclass and then install __hash__/__eq__
#

def test_event_dataclass_without_kwargs_sets_hash_and_eq():
    @event_util.dataclass()  # no kwargs branch inside util.dataclass  # [event.util]
    class E:
        event_id: str
        x: int = 0

    a = E(event_id="A", x=1)
    b = E(event_id="A", x=99)     # same event_id -> same hash, equal
    c = E(event_id="C", x=1)      # different event_id -> different hash, not equal

    # __hash__ should be derived from event_id
    assert hash(a) == hash(b)
    assert hash(a) != hash(c)

    # __eq__ uses event_util.event_eq, which compares hashes
    assert a == b
    assert a != c

#
# 2) dataclass() WITH kwargs: should honor kwargs (e.g., frozen=True) and still install __hash__/__eq__
#

def test_event_dataclass_with_kwargs_preserves_kwargs_and_sets_hash_eq():
    @event_util.dataclass(frozen=True)  # kwargs branch
    class E:
        event_id: str
        y: int = 0

    e1 = E(event_id="Z", y=1)
    # frozen=True should make the instance immutable
    with pytest.raises(dataclasses.FrozenInstanceError):
        e1.y = 2  # type: ignore[attr-defined]

    # __hash__ / __eq__ still installed
    e2 = E(event_id="Z", y=999)
    e3 = E(event_id="OTHER")
    assert hash(e1) == hash(e2) and e1 == e2
    assert hash(e1) != hash(e3) and e1 != e3

#
# 3) event_hash: explicitly uses instance.event_id
#

def test_event_hash_uses_event_id():
    class Dummy:
        def __init__(self, eid): self.event_id = eid
    d1, d2 = Dummy("K"), Dummy("K")
    assert event_util.event_hash(d1) == event_util.event_hash(d2)  # same event_id

#
# 4) event_eq compares hashes, not types or fields
#

def test_event_eq_compares_hashes_not_types():
    @event_util.dataclass()
    class E:
        event_id: str

    class Other:
        # Make it hash to the same value as E("SAME")
        def __hash__(self): return hash("SAME")

    e = E(event_id="SAME")
    o = Other()
    assert event_util.event_eq(e, o)  # equal because hashes match
