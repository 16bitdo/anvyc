"""Unit tests for anvyc.core.activity (CP-1 data collector)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from anvyc.core.activity import (
    collect_sessions,
    discover_session_roots,
    iter_session_files,
    parse_session,
)


def _write_session(path: Path, events: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


@pytest.fixture
def fake_claude_home(tmp_path: Path) -> Path:
    """합성 멀티계정 ~/.claude*/projects/ 트리.

    Layout:
      home/.claude/projects/proj-a/session-A.jsonl  (sessionId=A, tool_use 2회)
      home/.claude-edward/projects/proj-b/session-B.jsonl  (sessionId=B, tool_use 1회)
    """
    home = tmp_path / "home"
    home.mkdir()

    a_dir = home / ".claude" / "projects" / "proj-a"
    a_dir.mkdir(parents=True)
    _write_session(
        a_dir / "session-A.jsonl",
        [
            {
                "sessionId": "A",
                "type": "user",
                "timestamp": "2026-05-01T00:00:00Z",
                "cwd": "/x",
                "gitBranch": "main",
            },
            {
                "sessionId": "A",
                "type": "assistant",
                "timestamp": "2026-05-01T00:00:10Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "ok"},
                        {"type": "tool_use", "name": "Read", "input": {}},
                        {"type": "tool_use", "name": "Bash", "input": {}},
                    ],
                },
            },
            {"sessionId": "A", "type": "user", "timestamp": "2026-05-01T00:00:20Z"},
        ],
    )

    b_dir = home / ".claude-edward" / "projects" / "proj-b"
    b_dir.mkdir(parents=True)
    _write_session(
        b_dir / "session-B.jsonl",
        [
            {"sessionId": "B", "type": "user", "timestamp": "2026-05-02T01:00:00Z", "cwd": "/y"},
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

    return home


def test_discover_session_roots(fake_claude_home: Path) -> None:
    roots = discover_session_roots(home=fake_claude_home)
    assert len(roots) == 2
    paths_str = [str(r) for r in roots]
    assert any("/.claude/projects" in p for p in paths_str)
    assert any("/.claude-edward/projects" in p for p in paths_str)


def test_discover_session_roots_empty(tmp_path: Path) -> None:
    # ~/.claude* 디렉터리가 하나도 없는 환경
    roots = discover_session_roots(home=tmp_path)
    assert roots == []


def test_iter_session_files(fake_claude_home: Path) -> None:
    roots = discover_session_roots(home=fake_claude_home)
    files = list(iter_session_files(roots))
    assert len(files) == 2
    assert all(p.suffix == ".jsonl" for p in files)


def test_parse_session_basic(fake_claude_home: Path) -> None:
    roots = discover_session_roots(home=fake_claude_home)
    files = list(iter_session_files(roots))
    session_a = next(p for p in files if p.name == "session-A.jsonl")

    s = parse_session(session_a)
    assert s is not None
    assert s.session_id == "A"
    assert s.cwd == "/x"
    assert s.git_branch == "main"
    assert s.event_count == 3
    assert s.tool_call_count == 2
    assert dict(s.tools_used) == {"Read": 1, "Bash": 1}
    assert s.duration_seconds == 20.0


def test_parse_session_empty_file(tmp_path: Path) -> None:
    f = tmp_path / "empty.jsonl"
    f.write_text("\n", encoding="utf-8")
    assert parse_session(f) is None


def test_parse_session_no_session_id(tmp_path: Path) -> None:
    f = tmp_path / "no-sid.jsonl"
    _write_session(f, [{"type": "user", "timestamp": "2026-05-01T00:00:00Z"}])
    assert parse_session(f) is None


def test_parse_session_malformed_lines_skip(tmp_path: Path) -> None:
    """Invalid JSON 라인은 silent skip, 유효한 라인만 카운트."""
    f = tmp_path / "mixed.jsonl"
    f.write_text(
        "\n".join(
            [
                "not json",
                json.dumps({"sessionId": "M", "type": "user", "timestamp": "2026-05-01T00:00:00Z"}),
                "also not json",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    s = parse_session(f)
    assert s is not None
    assert s.session_id == "M"
    assert s.event_count == 1


def test_parse_session_nonexistent_path(tmp_path: Path) -> None:
    assert parse_session(tmp_path / "nope.jsonl") is None


def test_collect_sessions(fake_claude_home: Path) -> None:
    roots = discover_session_roots(home=fake_claude_home)
    sessions = collect_sessions(roots)
    assert len(sessions) == 2
    ids = sorted(s.session_id for s in sessions)
    assert ids == ["A", "B"]


def test_session_to_dict(fake_claude_home: Path) -> None:
    roots = discover_session_roots(home=fake_claude_home)
    sessions = collect_sessions(roots)
    a = next(s for s in sessions if s.session_id == "A")
    d = a.to_dict()
    assert d["session_id"] == "A"
    assert d["cwd"] == "/x"
    assert d["git_branch"] == "main"
    assert d["tool_call_count"] == 2
    assert d["tools_used"] == {"Read": 1, "Bash": 1}
    assert d["duration_seconds"] == 20.0
    assert d["event_count"] == 3
    assert d["started_at"] == "2026-05-01T00:00:00+00:00"
    assert d["ended_at"] == "2026-05-01T00:00:20+00:00"


def test_session_duration_none_when_no_timestamps(tmp_path: Path) -> None:
    f = tmp_path / "no-ts.jsonl"
    _write_session(f, [{"sessionId": "NT", "type": "user"}])
    s = parse_session(f)
    assert s is not None
    assert s.duration_seconds is None
    assert s.started_at is None
    assert s.ended_at is None


# --------------- aggregate_sessions / tool_call_ranking (CP-1 3/3) ---------------


def test_aggregate_sessions_basic(fake_claude_home: Path) -> None:
    from anvyc.core.activity import aggregate_sessions

    roots = discover_session_roots(home=fake_claude_home)
    sessions = collect_sessions(roots)
    agg = aggregate_sessions(sessions)

    assert agg["total_sessions"] == 2
    # A: 3 events / 2 tool calls, B: 2 events / 1 tool call
    assert agg["total_events"] == 5
    assert agg["total_tool_calls"] == 3
    # A duration = 20s, B duration = 5s
    assert agg["total_duration_seconds"] == 25.0
    assert agg["tools_used"] == {"Read": 2, "Bash": 1}
    assert agg["oldest_session_started_at"] == "2026-05-01T00:00:00+00:00"
    assert agg["newest_session_ended_at"] == "2026-05-02T01:00:05+00:00"


def test_aggregate_sessions_empty() -> None:
    from anvyc.core.activity import aggregate_sessions

    agg = aggregate_sessions([])
    assert agg["total_sessions"] == 0
    assert agg["total_events"] == 0
    assert agg["total_tool_calls"] == 0
    assert agg["total_duration_seconds"] == 0.0
    assert agg["tools_used"] == {}
    assert agg["oldest_session_started_at"] is None
    assert agg["newest_session_ended_at"] is None


def test_tool_call_ranking_full(fake_claude_home: Path) -> None:
    from anvyc.core.activity import tool_call_ranking

    roots = discover_session_roots(home=fake_claude_home)
    sessions = collect_sessions(roots)
    ranking = tool_call_ranking(sessions)

    # Read=2 (>Bash=1) so Read first
    assert ranking == [{"name": "Read", "count": 2}, {"name": "Bash", "count": 1}]


def test_tool_call_ranking_top(fake_claude_home: Path) -> None:
    from anvyc.core.activity import tool_call_ranking

    roots = discover_session_roots(home=fake_claude_home)
    sessions = collect_sessions(roots)
    ranking = tool_call_ranking(sessions, top=1)

    assert ranking == [{"name": "Read", "count": 2}]


def test_tool_call_ranking_empty() -> None:
    from anvyc.core.activity import tool_call_ranking

    assert tool_call_ranking([]) == []
    assert tool_call_ranking([], top=5) == []
