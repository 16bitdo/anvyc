from typing import Any

from anvyc.core.runs import Run, _parse_run, aggregate_runs


def parse(**extra: Any) -> Run:
    result = _parse_run(
        {"run_id": "r", "status": "succeeded", "agent": "codex", "cost_usd": 0.0, **extra}
    )
    assert result is not None
    return result


def test_codex_unknown_cost_excluded_from_percentile() -> None:
    result = aggregate_runs([parse(tokens={"input": 100, "output": 10, "cache_read": 800})])
    assert result["cost_unknown_runs"] == 1
    assert result["cost_observed_runs"] == 0
    assert result["p95_cost_usd"] is None
    assert result["total_tokens"] == 910


def test_unknown_and_partial_usage_distinct_from_observed_zero() -> None:
    records = [
        parse(measurement={"usage_available": False, "usage_final": False}),
        parse(measurement={"usage_available": True, "usage_final": False}, tokens={"input": 10}),
        parse(measurement={"usage_available": True, "usage_final": True}, tokens={"input": 0}),
    ]
    result = aggregate_runs(records)
    assert result["usage_unknown_runs"] == 1
    assert result["usage_partial_runs"] == 1
    assert result["usage_observed_runs"] == 2
    assert result["total_tokens"] == 10


def test_quality_and_context_distribution() -> None:
    record = parse(
        tokens={"input": 200, "output": 100, "cache_read": 800},
        measurement={
            "usage_available": True,
            "usage_final": True,
            "reasoning_effort": "medium",
            "cost_available": False,
        },
        completion={"status": "passed"},
    )
    result = aggregate_runs([record])
    assert result["by_completion_status"] == {"passed": 1}
    assert result["by_reasoning_effort"] == {"medium": 1}
    assert result["cache_input_ratio"] == 0.8


def test_real_claude_zero_cost_remains_known() -> None:
    result = aggregate_runs([parse(agent="claude_code")])
    assert result["cost_observed_runs"] == 1
    assert result["cost_unknown_runs"] == 0
    assert result["p95_cost_usd"] == 0.0


def test_invalid_cost_cannot_become_known_zero() -> None:
    for value in (None, True, float("nan"), -1):
        record = parse(cost_usd=value, measurement={"cost_available": True})
        assert not record.cost_available
        assert aggregate_runs([record])["p95_cost_usd"] is None
