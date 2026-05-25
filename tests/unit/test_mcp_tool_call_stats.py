"""tests/unit/test_mcp_tool_call_stats.py — CP-8 PR-D.

MCP server 의 tool_call_stats handler 가 ranking + blocked 의 dict 형식
으로 반환하는지 검증. PR-B 의 audit_log ingestion + 기존 tool_call_ranking
이 결합되어 control plane 의 'tool 호출 / 차단' 통합 view 를 노출한다.

PR-B 의 audit jsonl 위치는 ~/.config/cc-inspect/audit/ 기본 — 본 테스트는
monkeypatch 로 collect_block_events 의 audit_dir 만 격리한다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from anvyc.mcp.server import _dispatch


def _write_jsonl(path: Path, events: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


@pytest.fixture
def fake_audit_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """audit_log 의 기본 디렉토리를 tmp_path 로 patch.

    AUDIT_DIR_DEFAULT 를 변경하는 게 아니라 discover_audit_files 가 의존하는
    default 값을 직접 swap. 본 PR-D 의 _dispatch 는 collect_block_events()
    를 인자 없이 호출 → 기본 경로 사용 → 본 patch 가 적용됨.
    """
    from anvyc.core import audit_log

    monkeypatch.setattr(audit_log, "AUDIT_DIR_DEFAULT", tmp_path)
    return tmp_path


@pytest.fixture
def fake_no_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    """activity 의 session 수집을 빈 list 로 patch — ranking 무관 검증 격리."""
    from anvyc.core import activity

    monkeypatch.setattr(activity, "iter_session_files", lambda roots=None: iter([]))


def test_dispatch_returns_dict_with_two_keys(fake_audit_dir: Path, fake_no_sessions: None) -> None:
    result = _dispatch("tool_call_stats", {})
    assert isinstance(result, dict)
    assert set(result.keys()) == {"tool_call_ranking", "blocked"}


def test_blocked_empty_when_no_audit_files(fake_audit_dir: Path, fake_no_sessions: None) -> None:
    result = _dispatch("tool_call_stats", {})
    blocked = result["blocked"]
    assert blocked["total_blocks"] == 0
    assert blocked["by_hook"] == {}
    assert blocked["by_agent"] == {}
    assert blocked["oldest_block_at"] is None
    assert blocked["newest_block_at"] is None


def test_blocked_aggregates_audit_jsonl(fake_audit_dir: Path, fake_no_sessions: None) -> None:
    _write_jsonl(
        fake_audit_dir / "risk-gate-2026-05-25.jsonl",
        [
            {"ts": "2026-05-25T10:00:00Z", "hook": "destructive-keyword-block",
             "matcher": "Bash", "agent": "claude_code", "exit_code": 2,
             "command_redacted": "rm -rf /tmp/x"},
            {"ts": "2026-05-25T10:05:00Z", "hook": "destructive-keyword-block",
             "matcher": "Bash", "agent": "claude_code", "exit_code": 2,
             "command_redacted": "rm -rf /tmp/y"},
            {"ts": "2026-05-25T10:10:00Z", "hook": "aws-prod-account-confirm",
             "matcher": "Bash", "agent": "claude_code", "exit_code": 2,
             "command_redacted": "aws s3 ls --profile prod"},
        ],
    )
    result = _dispatch("tool_call_stats", {})
    blocked = result["blocked"]
    assert blocked["total_blocks"] == 3
    assert blocked["by_hook"] == {
        "destructive-keyword-block": 2,
        "aws-prod-account-confirm": 1,
    }
    assert blocked["by_agent"] == {"claude_code": 3}
    assert blocked["oldest_block_at"].startswith("2026-05-25T10:00:00")
    assert blocked["newest_block_at"].startswith("2026-05-25T10:10:00")


def test_ranking_top_argument(fake_audit_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`top` N 인자가 ranking 만 자르고 blocked 는 영향받지 않음."""
    from anvyc.core import activity

    # 4개 tool 호출 — top=2 면 상위 2개만
    fake_counter: dict[str, int] = {"Bash": 10, "Read": 5, "Edit": 3, "Write": 1}

    def fake_ranking(sessions: list[Any], top: int | None = None) -> list[dict[str, Any]]:
        items = sorted(fake_counter.items(), key=lambda kv: -kv[1])
        if top is not None:
            items = items[:top]
        return [{"name": n, "count": c} for n, c in items]

    monkeypatch.setattr(activity, "tool_call_ranking", fake_ranking)
    monkeypatch.setattr(activity, "collect_sessions", lambda agent=None: [])

    result = _dispatch("tool_call_stats", {"top": 2})
    assert len(result["tool_call_ranking"]) == 2
    assert result["tool_call_ranking"][0]["name"] == "Bash"
    assert result["tool_call_ranking"][1]["name"] == "Read"


def test_agent_unknown_raises_key_error(fake_audit_dir: Path) -> None:
    """alien --agent 명시는 collect_sessions 가 KeyError raise — MCP 에서 그대로 전파."""
    with pytest.raises(KeyError, match="unknown agent"):
        _dispatch("tool_call_stats", {"agent": "alienagent"})


def test_agent_stub_raises_not_implemented(fake_audit_dir: Path) -> None:
    """stub agent 명시는 NotImplementedError — MCP 에서 그대로 전파."""
    with pytest.raises(NotImplementedError):
        _dispatch("tool_call_stats", {"agent": "cursor"})


def test_blocked_unaffected_by_agent_arg(fake_audit_dir: Path, fake_no_sessions: None) -> None:
    """agent 인자는 ranking 만 영향 — blocked 통계는 audit jsonl 의 agent 필드 그대로."""
    _write_jsonl(
        fake_audit_dir / "risk-gate-2026-05-25.jsonl",
        [
            {"ts": "2026-05-25T10:00:00Z", "hook": "h1", "matcher": "Bash",
             "agent": "claude_code", "exit_code": 2, "command_redacted": "x"},
        ],
    )
    result = _dispatch("tool_call_stats", {"agent": "claude_code"})
    assert result["blocked"]["total_blocks"] == 1
    assert result["blocked"]["by_agent"] == {"claude_code": 1}
