"""tests/unit/test_audit_log.py — CP-8 PR-B audit ingestion.

검증 항목:
1. audit_dir 부재 → discover 빈 list
2. jsonl 파싱 — 정상 block 이벤트 정규화
3. 손상된 라인 / hook 필드 부재 → silent skip
4. aggregate — by_hook / by_agent / 시간 range
5. multi-file → 모두 합산
"""
from __future__ import annotations

import json
from pathlib import Path

from anvyc.core.audit_log import (
    BlockEvent,
    aggregate_block_events,
    collect_block_events,
    discover_audit_files,
    iter_block_events,
)


def _write_jsonl(path: Path, events: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


def test_discover_missing_dir_returns_empty(tmp_path: Path) -> None:
    assert discover_audit_files(tmp_path / "nope") == []


def test_discover_sorted_glob(tmp_path: Path) -> None:
    (tmp_path / "risk-gate-2026-05-02.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "risk-gate-2026-05-01.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("", encoding="utf-8")  # glob 외 파일
    found = discover_audit_files(tmp_path)
    assert [p.name for p in found] == [
        "risk-gate-2026-05-01.jsonl",
        "risk-gate-2026-05-02.jsonl",
    ]


def test_iter_normalizes_block_event(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "risk-gate-2026-05-25.jsonl",
        [
            {
                "ts": "2026-05-25T10:00:00Z",
                "hook": "destructive-keyword-block",
                "matcher": "Bash",
                "agent": "claude_code",
                "exit_code": 2,
                "command_redacted": "rm -rf /tmp/x",
            }
        ],
    )
    events = collect_block_events(tmp_path)
    assert len(events) == 1
    e = events[0]
    assert isinstance(e, BlockEvent)
    assert e.hook == "destructive-keyword-block"
    assert e.matcher == "Bash"
    assert e.agent == "claude_code"
    assert e.exit_code == 2
    assert e.ts is not None and e.ts.year == 2026
    assert e.line_number == 1


def test_iter_skips_corrupted_lines(tmp_path: Path) -> None:
    af = tmp_path / "risk-gate-2026-05-25.jsonl"
    af.write_text(
        "\n".join(
            [
                "not json at all",
                json.dumps({"hook": "destructive-keyword-block", "exit_code": 2}),
                "{ malformed",
                json.dumps({"no_hook_field": True}),  # hook 필드 부재 → skip
                "",  # 빈 줄
                json.dumps({"hook": "aws-prod-account-confirm", "exit_code": 2}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    events = collect_block_events(tmp_path)
    hooks = [e.hook for e in events]
    assert hooks == ["destructive-keyword-block", "aws-prod-account-confirm"]


def test_aggregate_by_hook_and_agent(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "risk-gate-2026-05-25.jsonl",
        [
            {"ts": "2026-05-25T10:00:00Z", "hook": "destructive-keyword-block", "agent": "claude_code", "exit_code": 2},
            {"ts": "2026-05-25T10:05:00Z", "hook": "destructive-keyword-block", "agent": "claude_code", "exit_code": 2},
            {"ts": "2026-05-25T10:10:00Z", "hook": "aws-prod-account-confirm", "agent": "claude_code", "exit_code": 2},
        ],
    )
    events = collect_block_events(tmp_path)
    agg = aggregate_block_events(events)
    assert agg["total_blocks"] == 3
    assert agg["by_hook"] == {"destructive-keyword-block": 2, "aws-prod-account-confirm": 1}
    assert agg["by_agent"] == {"claude_code": 3}
    assert agg["oldest_block_at"].startswith("2026-05-25T10:00:00")
    assert agg["newest_block_at"].startswith("2026-05-25T10:10:00")


def test_multi_file_aggregation(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "risk-gate-2026-05-24.jsonl",
        [{"ts": "2026-05-24T12:00:00Z", "hook": "h1", "agent": "claude_code", "exit_code": 2}],
    )
    _write_jsonl(
        tmp_path / "risk-gate-2026-05-25.jsonl",
        [
            {"ts": "2026-05-25T01:00:00Z", "hook": "h1", "agent": "claude_code", "exit_code": 2},
            {"ts": "2026-05-25T02:00:00Z", "hook": "h2", "agent": "claude_code", "exit_code": 2},
        ],
    )
    events = collect_block_events(tmp_path)
    assert len(events) == 3
    # source_path 가 각각 다른 파일을 가리키는지 확인
    sources = {e.source_path.name for e in events}
    assert sources == {"risk-gate-2026-05-24.jsonl", "risk-gate-2026-05-25.jsonl"}


def test_empty_aggregate(tmp_path: Path) -> None:
    agg = aggregate_block_events([])
    assert agg["total_blocks"] == 0
    assert agg["by_hook"] == {}
    assert agg["by_agent"] == {}
    assert agg["oldest_block_at"] is None
    assert agg["newest_block_at"] is None


def test_iter_yields_in_file_order(tmp_path: Path) -> None:
    """iter_block_events 는 정렬된 파일 순서 + 파일 내 line 순서로 yield."""
    _write_jsonl(
        tmp_path / "risk-gate-2026-05-25.jsonl",
        [
            {"hook": "first", "exit_code": 2},
            {"hook": "second", "exit_code": 2},
        ],
    )
    hooks = [e.hook for e in iter_block_events(tmp_path)]
    assert hooks == ["first", "second"]
