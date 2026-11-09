"""Gates of the pack v2 result (M3 Task 7). The gate values are fixed by the plan."""

from __future__ import annotations

from scripts.m3_pack_result import GATES, failed_gates


def test_gate_values_are_the_plan_values():
    assert GATES == {
        "min_recipes": 2500,
        "min_recipes_fully_read": 0.60,
        "max_core_bytes": 3_145_728,
    }


def test_passing_numbers_pass_and_each_failure_is_named():
    assert failed_gates(2500, 0.60, 3_145_728) == []
    assert len(failed_gates(2499, 0.60, 1)) == 1
    assert len(failed_gates(3000, 0.5999, 1)) == 1
    assert len(failed_gates(3000, 0.9, 3_145_729)) == 1
    assert len(failed_gates(0, 0.0, 10**9)) == 3
