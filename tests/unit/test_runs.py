"""run-record reader / 집계 테스트 (CP-14 원장 흡수)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from anvyc.core.runs import aggregate_runs, collect_runs, discover_run_files


def _rec(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema_version": 1,
        "run_id": "r1",
        "status": "succeeded",
        "agent": "claude_code",
        "model": "opus",
        "cwd": "/t",
        "started_at": "2026-05-30T10:00:00Z",
        "stopped_at": "2026-05-30T10:01:00Z",
        "duration_s": 60.0,
        "exit_reason": "completed",
        "exit_code": 0,
        "tool_calls": 2,
        "tokens": {"input": 10, "output": 5, "cache_read": 0, "cache_creation": 100},
        "cost_usd": 0.01,
        "machine_id": "m1",
        "error": None,
    }
    base.update(kw)
    return base


def _write(runs_dir: Path, date: str, records: list[dict[str, Any]]) -> None:
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"{date}.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )


def test_collect_runs_parses(tmp_path: Path) -> None:
    _write(tmp_path, "2026-05-30", [_rec(run_id="a"), _rec(run_id="b", status="failed")])
    runs = collect_runs(tmp_path)
    assert {r.run_id for r in runs} == {"a", "b"}


def test_tokens_total_summed(tmp_path: Path) -> None:
    _write(tmp_path, "2026-05-30", [_rec()])
    assert collect_runs(tmp_path)[0].tokens_total == 115  # 10+5+0+100


def test_skips_corrupt_and_missing_run_id(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "2026-05-30.jsonl").write_text(
        json.dumps(_rec(run_id="ok")) + "\n"
        + "{ broken json\n"
        + json.dumps({"status": "x"}) + "\n",  # run_id 없음
        encoding="utf-8",
    )
    assert [r.run_id for r in collect_runs(tmp_path)] == ["ok"]


def test_missing_dir_returns_empty(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    assert discover_run_files(missing) == []
    assert collect_runs(missing) == []


def test_agent_filter(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "2026-05-30",
        [_rec(run_id="a", agent="claude_code"), _rec(run_id="b", agent="cursor")],
    )
    assert {r.run_id for r in collect_runs(tmp_path, agent="cursor")} == {"b"}


def test_collect_sorted_by_started_at(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "2026-05-30",
        [
            _rec(run_id="late", started_at="2026-05-30T12:00:00Z"),
            _rec(run_id="early", started_at="2026-05-30T08:00:00Z"),
        ],
    )
    assert [r.run_id for r in collect_runs(tmp_path)] == ["early", "late"]


def test_aggregate(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "2026-05-30",
        [
            _rec(run_id="a", status="succeeded", exit_reason="completed", cost_usd=0.01, tool_calls=2),
            _rec(run_id="b", status="failed", exit_reason="error", cost_usd=0.02, tool_calls=1),
            _rec(run_id="c", status="aborted", exit_reason="budget_exceeded", cost_usd=0.03, tool_calls=0),
        ],
    )
    agg = aggregate_runs(collect_runs(tmp_path))
    assert agg["total_runs"] == 3
    assert agg["by_status"] == {"succeeded": 1, "failed": 1, "aborted": 1}
    assert agg["by_exit_reason"]["budget_exceeded"] == 1
    assert round(agg["total_cost_usd"], 6) == 0.06
    assert agg["total_tool_calls"] == 3
    assert agg["oldest_run_started_at"] == "2026-05-30T10:00:00Z"


def test_aggregate_empty() -> None:
    agg = aggregate_runs([])
    assert agg["total_runs"] == 0
    assert agg["by_status"] == {}
    assert agg["oldest_run_started_at"] is None


def test_mcp_run_summary_dispatch(tmp_path: Path, monkeypatch: Any) -> None:
    _write(tmp_path, "2026-05-30", [_rec(run_id="a"), _rec(run_id="b")])
    monkeypatch.setattr("anvyc.core.runs.RUNS_DIR_DEFAULT", tmp_path)
    from anvyc.mcp.server import _dispatch

    result = _dispatch("run_summary", {})
    assert result["total_runs"] == 2
