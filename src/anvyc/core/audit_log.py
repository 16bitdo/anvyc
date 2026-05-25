"""Audit log ingestion (CP-8 PR-B).

`~/.config/cc-inspect/audit/risk-gate-*.jsonl` 의 block 이벤트를 read-only
로 수집·정규화한다. CP-8 PR-A 의 hook audit emit (rbr templates/hooks/
pre-tool-use/*.sh) 가 출력하는 jsonl 의 소비자.

후속 PR 에서 `tool_call_stats` 에 'blocked' 카테고리로 노출 (CP-7 Phase
B 의 multi-agent dispatch 와 결합).

본 모듈의 형식 (BlockEvent) 은 PR-A 의 audit jsonl schema 와 1:1 — schema
변경 시 양쪽 동시 갱신.
"""
from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

AUDIT_DIR_DEFAULT = Path.home() / ".config" / "cc-inspect" / "audit"
AUDIT_FILE_GLOB = "risk-gate-*.jsonl"


@dataclass
class BlockEvent:
    """audit jsonl 한 줄의 정규화. PR-A 의 schema 와 1:1 매핑."""

    ts: datetime | None
    hook: str
    matcher: str
    agent: str
    exit_code: int
    command_redacted: str
    source_path: Path
    line_number: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts.isoformat() if self.ts else None,
            "hook": self.hook,
            "matcher": self.matcher,
            "agent": self.agent,
            "exit_code": self.exit_code,
            "command_redacted": self.command_redacted,
            "source_path": str(self.source_path),
            "line_number": self.line_number,
        }


def discover_audit_files(audit_dir: Path | None = None) -> list[Path]:
    """audit jsonl 파일 목록 (정렬). audit_dir 미존재 시 빈 list."""
    base = audit_dir or AUDIT_DIR_DEFAULT
    if not base.is_dir():
        return []
    return sorted(base.glob(AUDIT_FILE_GLOB))


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    raw = value
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def iter_block_events(
    audit_dir: Path | None = None,
    agent: str | None = None,
) -> Iterator[BlockEvent]:
    """모든 audit jsonl 의 block 이벤트 yield.

    손상된 라인 / 형식 불일치는 silent skip (read-only collector 의 안전
    기본값, activity.py 와 동일 패턴).

    CP-11 PR-11E — agent filter:
      - agent=None (기본): 모든 agent 의 event yield
      - agent='<name>': 해당 agent 의 event 만 yield. audit jsonl 의
        'agent' 필드와 정확히 일치하는 event 만.
    """
    for path in discover_audit_files(audit_dir):
        try:
            with path.open(encoding="utf-8") as f:
                for line_no, raw in enumerate(f, start=1):
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    hook = event.get("hook")
                    if not isinstance(hook, str) or not hook:
                        continue
                    event_agent = str(event.get("agent", ""))
                    if agent is not None and event_agent != agent:
                        continue
                    yield BlockEvent(
                        ts=_parse_timestamp(event.get("ts")),
                        hook=hook,
                        matcher=str(event.get("matcher", "")),
                        agent=event_agent,
                        exit_code=int(event.get("exit_code", 0)) if isinstance(event.get("exit_code"), int) else 0,
                        command_redacted=str(event.get("command_redacted", "")),
                        source_path=path,
                        line_number=line_no,
                    )
        except OSError:
            continue


def collect_block_events(
    audit_dir: Path | None = None,
    agent: str | None = None,
) -> list[BlockEvent]:
    return list(iter_block_events(audit_dir, agent=agent))


def aggregate_block_events(events: list[BlockEvent]) -> dict[str, Any]:
    """block 이벤트 통계 — hook 별 count / agent 별 count / 시간 range.

    `tool_call_stats` 의 'blocked' 카테고리에 합류 예정 (후속 PR).
    """
    by_hook: Counter[str] = Counter(e.hook for e in events)
    by_agent: Counter[str] = Counter(e.agent for e in events)
    timestamps = [e.ts for e in events if e.ts is not None]
    oldest = min(timestamps) if timestamps else None
    newest = max(timestamps) if timestamps else None
    return {
        "total_blocks": len(events),
        "by_hook": dict(by_hook),
        "by_agent": dict(by_agent),
        "oldest_block_at": oldest.isoformat() if oldest else None,
        "newest_block_at": newest.isoformat() if newest else None,
    }
