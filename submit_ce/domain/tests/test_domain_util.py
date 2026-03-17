"""Test util.py under domain"""
import datetime as _dt

from submit_ce.domain.util import (
    get_tzaware_utc_now,
    dict_coerce,
    list_coerce,
)

def test_get_tzaware_utc_now_is_aware_and_utc():
    now = get_tzaware_utc_now()  # should be tz-aware in UTC
    assert now.tzinfo is not None
    assert now.utcoffset() == _dt.timedelta(0)

def test_dict_coerce_mixed_items():
    # factory that consumes dicts only
    def factory(**kw):
        return ("ok", kw["a"] + kw.get("b", 0))

    data = {
        "e1": {"a": 1, "b": 2},  # will be coerced via factory(**value)
        "e2": 42,                # left as-is (non-dict branch)
    }
    out = dict_coerce(factory, data)
    assert out["e1"] == ("ok", 3)
    assert out["e2"] == 42  # not coerced

def test_list_coerce_filters_and_coerces_only_dicts():
    def factory(**kw):
        return kw["x"] * 10

    data = [{"x": 3}, "skip-me", {"x": 7}, 99]
    out = list_coerce(factory, data)  # includes only dict items
    assert out == [30, 70]
