"""`anvyc runs ...` CLI 테스트 (CP-14 원장 흡수)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from anvyc.cli import app

runner = CliRunner()


@pytest.fixture
def fake_runs(tmp_path: Path, monkeypatch: Any) -> Path:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True)
    rec = {
        "schema_version": 1,
        "run_id": "9f1c2e84-aaaa",
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
        "cost_usd": 0.0123,
        "machine_id": "m1",
        "error": None,
    }
    (runs_dir / "2026-05-30.jsonl").write_text(
        json.dumps(rec) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr("anvyc.core.runs.RUNS_DIR_DEFAULT", runs_dir)
    return runs_dir


def test_runs_summary_table(fake_runs: Path) -> None:
    result = runner.invoke(app, ["runs", "summary"])
    assert result.exit_code == 0, result.output
    assert "total runs" in result.output


def test_runs_summary_json(fake_runs: Path) -> None:
    result = runner.invoke(app, ["runs", "summary", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["total_runs"] == 1
    assert data["by_status"] == {"succeeded": 1}
    assert data["total_cost_usd"] == 0.0123


def test_runs_summary_empty(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr("anvyc.core.runs.RUNS_DIR_DEFAULT", tmp_path / "empty")
    result = runner.invoke(app, ["runs", "summary"])
    assert result.exit_code == 0
    assert "no anvyx run-record" in result.output


def test_runs_list_json(fake_runs: Path) -> None:
    result = runner.invoke(app, ["runs", "list", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert data[0]["run_id"] == "9f1c2e84-aaaa"
    assert data[0]["tokens_total"] == 115


def test_runs_list_table(fake_runs: Path) -> None:
    # 80-col CliRunner 폭에서 rich 가 셀을 말줄임하므로 헤더로 렌더 확인
    # (내용 정확성은 test_runs_list_json 이 검증).
    result = runner.invoke(app, ["runs", "list"])
    assert result.exit_code == 0
    assert "status" in result.output


def test_runs_list_agent_filter_excludes(fake_runs: Path) -> None:
    result = runner.invoke(app, ["runs", "list", "--agent", "cursor", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == []
