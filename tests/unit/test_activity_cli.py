"""Unit tests for `anvyc activity` CLI command (CP-1 2/3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from anvyc.cli import app


def _write_session(path: Path, events: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


@pytest.fixture
def fake_claude_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """합성 ~/.claude*/projects/ + HOME env monkeypatch (Path.home() 위임)."""
    home = tmp_path / "home"
    home.mkdir()

    a_dir = home / ".claude" / "projects" / "proj-a"
    a_dir.mkdir(parents=True)
    _write_session(
        a_dir / "session-A.jsonl",
        [
            {
                "sessionId": "Aaaaaaaa-cli",
                "type": "user",
                "timestamp": "2026-05-01T00:00:00Z",
                "cwd": "/x",
                "gitBranch": "main",
            },
            {
                "sessionId": "Aaaaaaaa-cli",
                "type": "assistant",
                "timestamp": "2026-05-01T00:00:10Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "name": "Read"},
                        {"type": "tool_use", "name": "Bash"},
                    ],
                },
            },
        ],
    )

    monkeypatch.setenv("HOME", str(home))
    return home


def test_activity_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["activity", "--help"])
    assert result.exit_code == 0
    # typer 가 docstring 첫 줄을 헬프로 사용 — "session" 키워드 등장 확인
    assert "session" in result.output.lower() or "activity" in result.output.lower()


def test_activity_default(fake_claude_home: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["activity"])
    assert result.exit_code == 0, result.output
    assert "1 session(s) found" in result.output
    # session_id 첫 8자 ("Aaaaaaaa")
    assert "Aaaaaaaa" in result.output
    # tool 사용 표시
    assert "Read=1" in result.output
    assert "Bash=1" in result.output


def test_activity_json(fake_claude_home: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["activity", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) == 1
    item = data[0]
    assert item["session_id"] == "Aaaaaaaa-cli"
    assert item["cwd"] == "/x"
    assert item["git_branch"] == "main"
    assert item["tool_call_count"] == 2
    assert item["tools_used"] == {"Read": 1, "Bash": 1}


def test_activity_empty_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home-empty"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    runner = CliRunner()
    result = runner.invoke(app, ["activity"])
    assert result.exit_code == 0
    assert "no Claude Code session" in result.output


def test_activity_json_empty_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home-empty"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    runner = CliRunner()
    result = runner.invoke(app, ["activity", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == []


def test_activity_limit_zero_returns_empty(fake_claude_home: Path) -> None:
    """--limit 0 은 (limit is not None) 분기로 빈 결과를 반환해야 한다."""
    runner = CliRunner()
    result = runner.invoke(app, ["activity", "--limit", "0", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == []


def test_activity_limit_one(fake_claude_home: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["activity", "--limit", "1", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 1
