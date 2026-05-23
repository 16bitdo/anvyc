"""Claude Code session log audit collector.

CP-1 (16bitdo/anvyc#28) 의 첫 단계 — `~/.claude*/projects/*/*.jsonl` (Claude Code 의
session transcript) 를 read-only 로 수집·정규화한다.

후속 PR 에서 CLI (`anvyc activity`) + MCP tool (`activity_summary`,
`tool_call_stats`) 이 본 모듈을 소비한다 (role-based-ruleset DESIGN §7.2 C3 contract).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

CLAUDE_HOME_GLOB = ".claude*"
PROJECTS_DIR = "projects"


@dataclass
class Session:
    """단일 Claude Code session 의 정규화된 메타데이터.

    jsonl 의 모든 이벤트를 보존하지 않고 audit / observability 에 필요한 요약만 유지.
    """

    session_id: str
    source_path: Path
    cwd: str | None = None
    git_branch: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    event_count: int = 0
    tool_call_count: int = 0
    tools_used: Counter[str] = field(default_factory=Counter)

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.ended_at:
            return (self.ended_at - self.started_at).total_seconds()
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "source_path": str(self.source_path),
            "cwd": self.cwd,
            "git_branch": self.git_branch,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_seconds": self.duration_seconds,
            "event_count": self.event_count,
            "tool_call_count": self.tool_call_count,
            "tools_used": dict(self.tools_used),
        }


def discover_session_roots(home: Path | None = None) -> list[Path]:
    """멀티계정 환경의 모든 `~/.claude*/projects` 디렉터리 검색.

    예: `~/.claude/projects`, `~/.claude-edward/projects`, `~/.claude-jklee/projects`.
    심볼릭 링크가 디렉터리를 가리키면 그대로 포함한다.
    """
    base = home or Path.home()
    roots: list[Path] = []
    for entry in sorted(base.glob(CLAUDE_HOME_GLOB)):
        proj = entry / PROJECTS_DIR
        if proj.is_dir():
            roots.append(proj)
    return roots


def iter_session_files(roots: list[Path] | None = None) -> Iterator[Path]:
    """모든 session jsonl 파일을 yield.

    `roots` 미지정 시 `discover_session_roots()` 결과를 사용한다.
    경로 정렬 (sorted) 으로 결정론적 순회를 보장한다.
    """
    if roots is None:
        roots = discover_session_roots()
    for root in roots:
        for path in sorted(root.glob("*/*.jsonl")):
            if path.is_file():
                yield path


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


def _extract_tool_calls(message: Any) -> list[str]:
    """assistant message 의 content array 에서 `tool_use` 블록의 name 을 수집.

    Anthropic 메시지 형식: `{role: 'assistant', content: [{type: 'tool_use', name: '<tool>'}]}`.
    형식 불일치는 silent skip — read-only collector 의 안전 기본값.
    """
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []
    names: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            name = block.get("name")
            if isinstance(name, str):
                names.append(name)
    return names


def parse_session(path: Path) -> Session | None:
    """단일 jsonl 파일을 파싱해 Session 으로 정규화.

    파일이 비었거나 session id 가 발견되지 않으면 None.
    parsing 중 한 줄이 invalid JSON 이어도 그 줄만 skip 하고 계속 진행한다
    (Claude Code 가 append-only 로 기록하는 transcript 의 부분 손상 허용).
    """
    session_id: str | None = None
    cwd: str | None = None
    git_branch: str | None = None
    started: datetime | None = None
    ended: datetime | None = None
    event_count = 0
    tool_calls: Counter[str] = Counter()

    try:
        with path.open(encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                event_count += 1

                if not isinstance(event, dict):
                    continue

                if session_id is None:
                    sid = event.get("sessionId")
                    if isinstance(sid, str):
                        session_id = sid

                if cwd is None:
                    c = event.get("cwd")
                    if isinstance(c, str):
                        cwd = c

                if git_branch is None:
                    gb = event.get("gitBranch")
                    if isinstance(gb, str) and gb:
                        git_branch = gb

                ts = _parse_timestamp(event.get("timestamp"))
                if ts:
                    if started is None or ts < started:
                        started = ts
                    if ended is None or ts > ended:
                        ended = ts

                if event.get("type") == "assistant":
                    for name in _extract_tool_calls(event.get("message")):
                        tool_calls[name] += 1
    except OSError:
        return None

    if not session_id:
        return None

    return Session(
        session_id=session_id,
        source_path=path,
        cwd=cwd,
        git_branch=git_branch,
        started_at=started,
        ended_at=ended,
        event_count=event_count,
        tool_call_count=sum(tool_calls.values()),
        tools_used=tool_calls,
    )


def collect_sessions(roots: list[Path] | None = None) -> list[Session]:
    """모든 session 을 파싱해 리스트로 반환 (session_id 없으면 제외)."""
    sessions: list[Session] = []
    for path in iter_session_files(roots):
        s = parse_session(path)
        if s is not None:
            sessions.append(s)
    return sessions
