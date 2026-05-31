"""CP-16 P2a — runs.py self_status/gate_blocked/repo 파싱 + percentile/분포/scope."""

import json
from pathlib import Path

from anvyc.core.runs import Run, _parse_run, _percentile, aggregate_runs, collect_runs


def _run(**kw: object) -> Run:
    obj = {"run_id": "r", "status": "succeeded", **kw}
    r = _parse_run(obj)
    assert r is not None
    return r


def test_parse_self_status_gate_repo() -> None:
    r = _run(self_status="blocked", repo="16bitdo/x", gate={"blocked": True})
    assert r.self_status == "blocked"
    assert r.gate_blocked is True
    assert r.repo == "16bitdo/x"


def test_parse_defaults_when_absent() -> None:
    r = _run()
    assert r.self_status is None
    assert r.gate_blocked is False
    assert r.repo is None


def test_aggregate_self_status_distribution_and_blocked() -> None:
    runs = [
        _run(self_status="done"),
        _run(self_status="blocked", gate={"blocked": True}),
        _run(self_status="done"),
    ]
    agg = aggregate_runs(runs)
    assert agg["by_self_status"] == {"done": 2, "blocked": 1}
    assert agg["blocked_count"] == 1


def test_aggregate_percentile_duration() -> None:
    runs = [_run(duration_s=float(v)) for v in (10, 20, 30, 40, 100)]
    agg = aggregate_runs(runs)
    assert agg["p50_duration_s"] == 30.0
    assert agg["p95_duration_s"] is not None and agg["p95_duration_s"] > 40.0


def test_percentile_helper() -> None:
    assert _percentile([], 0.5) is None
    assert _percentile([5.0], 0.95) == 5.0
    assert _percentile([10.0, 20.0, 30.0], 0.5) == 20.0


def test_repo_scope_filter(tmp_path: Path) -> None:
    (tmp_path / "2026-05-31.jsonl").write_text(
        json.dumps({"run_id": "a", "status": "succeeded", "repo": "16bitdo/x"})
        + "\n"
        + json.dumps({"run_id": "b", "status": "succeeded", "repo": "16bitdo/y"})
        + "\n",
        encoding="utf-8",
    )
    assert [r.run_id for r in collect_runs(tmp_path, repo="16bitdo/x")] == ["a"]
