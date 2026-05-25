"""anvyc MCP server activity tool dispatch 테스트 (CP-1 3/3).

[mcp] extra 미설치 환경에서는 importorskip 로 자동 skip.
실제 stdio round-trip 은 manual smoke. 본 파일은 _dispatch handler 의
activity_summary / tool_call_stats unit-level 검증.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("mcp")  # [mcp] extra 미설치 시 모듈 전체 skip


def _write_session(path: Path, events: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


@pytest.fixture
def fake_claude_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """합성 ~/.claude*/projects/ + HOME monkeypatch."""
    home = tmp_path / "home"
    home.mkdir()

    a = home / ".claude" / "projects" / "proj-a" / "session-A.jsonl"
    _write_session(
        a,
        [
            {
                "sessionId": "A",
                "type": "user",
                "timestamp": "2026-05-01T00:00:00Z",
                "cwd": "/x",
            },
            {
                "sessionId": "A",
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

    b = home / ".claude-edward" / "projects" / "proj-b" / "session-B.jsonl"
    _write_session(
        b,
        [
            {"sessionId": "B", "type": "user", "timestamp": "2026-05-02T01:00:00Z"},
            {
                "sessionId": "B",
                "type": "assistant",
                "timestamp": "2026-05-02T01:00:05Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "name": "Read"}],
                },
            },
        ],
    )

    monkeypatch.setenv("HOME", str(home))

    # CP-8 PR-D: audit_log 의 AUDIT_DIR_DEFAULT 는 import 시점에 evaluated 되어
    # HOME setenv 만으로는 격리 안 됨 — 실머신 ~/.config/cc-inspect/audit 누설
    # 방지를 위해 명시적으로 monkeypatch.
    from anvyc.core import audit_log

    monkeypatch.setattr(audit_log, "AUDIT_DIR_DEFAULT", tmp_path / "no-audit")

    # CP-10 (v5): cursor adapter 가 실머신 Cursor SQLite read — fake_claude_home
    # 안에서도 본 머신 데이터 누설 차단 위해 명시적 격리.
    from anvyc.agents import cursor as cursor_mod

    monkeypatch.setattr(cursor_mod, "DEFAULT_CURSOR_USER_DIR", tmp_path / "no-cursor")
    monkeypatch.delenv("ANVYC_CURSOR_USER_DIR", raising=False)

    return home


def test_dispatch_activity_summary(fake_claude_home: Path) -> None:
    from anvyc.mcp.server import _dispatch

    result = _dispatch("activity_summary", {})

    assert result["total_sessions"] == 2
    # A: 2 events / 2 tool calls, B: 2 events / 1 tool call
    assert result["total_events"] == 4
    assert result["total_tool_calls"] == 3
    # A: 10s, B: 5s
    assert result["total_duration_seconds"] == 15.0
    assert result["tools_used"] == {"Read": 2, "Bash": 1}
    assert result["oldest_session_started_at"] == "2026-05-01T00:00:00+00:00"
    assert result["newest_session_ended_at"] == "2026-05-02T01:00:05+00:00"


def test_dispatch_activity_summary_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home-empty"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    # CP-10 (v5): cursor 격리 — 실머신 SQLite 누설 차단.
    from anvyc.agents import cursor as cursor_mod

    monkeypatch.setattr(cursor_mod, "DEFAULT_CURSOR_USER_DIR", tmp_path / "no-cursor")
    monkeypatch.delenv("ANVYC_CURSOR_USER_DIR", raising=False)

    from anvyc.mcp.server import _dispatch

    result = _dispatch("activity_summary", {})

    assert result["total_sessions"] == 0
    assert result["tools_used"] == {}
    assert result["oldest_session_started_at"] is None


def test_dispatch_tool_call_stats_full(fake_claude_home: Path) -> None:
    """CP-8 PR-D — 반환 형식이 list → dict ({tool_call_ranking, blocked})."""
    from anvyc.mcp.server import _dispatch

    result = _dispatch("tool_call_stats", {})

    assert isinstance(result, dict)
    assert result["tool_call_ranking"] == [
        {"name": "Read", "count": 2},
        {"name": "Bash", "count": 1},
    ]
    # audit_dir 부재 (fake_claude_home 은 ~/.claude* 만 patch) → blocked 빈 통계.
    assert result["blocked"]["total_blocks"] == 0
    assert result["blocked"]["by_hook"] == {}


def test_dispatch_tool_call_stats_top(fake_claude_home: Path) -> None:
    """top 인자가 ranking 만 자르고 blocked 통계는 영향받지 않음 (CP-8 PR-D)."""
    from anvyc.mcp.server import _dispatch

    result = _dispatch("tool_call_stats", {"top": 1})

    assert isinstance(result, dict)
    assert result["tool_call_ranking"] == [{"name": "Read", "count": 2}]
    assert result["blocked"]["total_blocks"] == 0


def test_dispatch_tool_call_stats_invalid_top(fake_claude_home: Path) -> None:
    """top 이 int 가 아니면 ranking 전체 반환 (defensive fallback)."""
    from anvyc.mcp.server import _dispatch

    result = _dispatch("tool_call_stats", {"top": "bogus"})

    assert isinstance(result, dict)
    assert len(result["tool_call_ranking"]) == 2


def test_dispatch_unknown_tool_raises() -> None:
    from anvyc.mcp.server import _dispatch

    with pytest.raises(ValueError, match="unknown tool"):
        _dispatch("not_a_tool", {})
