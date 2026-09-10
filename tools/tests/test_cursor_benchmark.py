from copy import deepcopy

import pytest

from benchmarks.cursor_database import require_indexed_limit, selection_queries, timed


@pytest.mark.parametrize(
    "direction,comparison,order", [("next", ">", "asc"), ("previous", "<", "desc")]
)
def test_selection_shapes_preserve_strict_direction_and_explicit_wrap(direction, comparison, order):
    seek, wrap = selection_queries("seek", direction)
    assert f"item.position {comparison} %s" in seek
    assert seek.count("%s") == 2 and wrap.count("%s") == 1
    assert seek.endswith(f"item.position {order} limit 1")
    assert wrap.endswith(f"item.position {order} limit 1")
    assert "case when" not in seek + wrap
    (legacy,) = selection_queries("case", direction)
    assert f"case when item.position {comparison} %s then 0 else 1 end" in legacy
    with pytest.raises(ValueError):
        selection_queries("seek", "resume")


def test_plan_gate_requires_real_index_seek_not_just_one_output_row():
    good = {
        "Plan": {
            "Node Type": "Limit",
            "Actual Rows": 1,
            "Plans": [
                {
                    "Node Type": "Index Only Scan",
                    "Actual Rows": 1,
                    "Index Cond": "(batch_id = synthetic) AND (position > 500)",
                }
            ],
        }
    }
    require_indexed_limit(good, seek=True)
    for changes in (
        {"Node Type": "Sort"},
        {"Node Type": "Seq Scan"},
        {"Node Type": "Bitmap Heap Scan"},
        {"Node Type": "Result"},
        {"Index Cond": "batch_id = synthetic"},
        {"Index Cond": "position > 500"},
        {"Actual Rows": 1000},
        {"Rows Removed by Filter": 999},
    ):
        bad = deepcopy(good)
        bad["Plan"]["Plans"][0].update(changes)
        with pytest.raises(AssertionError):
            require_indexed_limit(bad, seek=True)
    wrap = deepcopy(good)
    wrap["Plan"]["Plans"][0]["Index Cond"] = "batch_id = synthetic"
    require_indexed_limit(wrap, seek=False)
    wrap["Plan"]["Actual Rows"] = 2
    with pytest.raises(AssertionError):
        require_indexed_limit(wrap, seek=False)


def test_timings_discard_warmups_but_keep_every_sample(monkeypatch):
    ticks = iter(range(60))
    calls = []
    monkeypatch.setattr("benchmarks.cursor_database.time.perf_counter_ns", lambda: next(ticks))
    report = timed(lambda: calls.append(True), 20)
    assert len(calls) == 30
    assert report["samples_ms"] == [0.000001] * 20
    assert report["p50_ms"] == report["p95_ms"] == 0.000001
