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


def collect_sessions(
    roots: list[Path] | None = None,
    agent: str | None = None,
) -> list[Session]:
    """모든 session 을 파싱해 리스트로 반환 (session_id 없으면 제외).

    CP-7 Phase B — agent 별 dispatch:
      - agent=None: 모든 등록된 AGENT_REGISTRY adapter 의 session union.
        stub adapter (Cursor/Codex) 의 NotImplementedError 는 silent skip
        (현재 동작과 byte-equal 보장 — Claude 만 impl).
      - agent="<name>": 해당 adapter 만 dispatch. 미등록은 KeyError,
        stub 은 NotImplementedError raise (CLI/MCP 가 사용자 메시지로 변환).

    legacy path: roots 명시 시 agent 인자 금지 (ValueError). roots 만
    사용하면 본 함수의 이전 동작 (top-level iter_session_files / parse_session)
    이 유지된다.
    """
    if roots is not None and agent is not None:
        raise ValueError("collect_sessions: roots 와 agent 를 함께 지정할 수 없습니다.")

    if agent is not None:
        # 단일 agent dispatch — registry 거침. stub 은 raise (silent 금지).
        from anvyc.agents import get_agent

        adapter = get_agent(agent)
        sessions: list[Session] = []
        for path in adapter.discover_session_files():
            s = adapter.parse_session(path)
            if s is not None:
                sessions.append(s)
        return sessions

    if roots is None:
        # CP-7 기본 경로: 모든 등록 agent 의 union. stub 의 NotImplementedError
        # 는 union 모드에서는 skip — 사용자가 단일 agent 를 명시했을 때만 raise.
        from anvyc.agents import AGENT_REGISTRY

        sessions = []
        for adapter in AGENT_REGISTRY.values():
            try:
                for path in adapter.discover_session_files():
                    s = adapter.parse_session(path)
                    if s is not None:
                        sessions.append(s)
            except NotImplementedError:
                continue
        return sessions

    # legacy: roots 명시 — 이전 직접 호출 경로 보존 (caller 가 roots 를 컨트롤).
    sessions = []
    for path in iter_session_files(roots):
        s = parse_session(path)
        if s is not None:
            sessions.append(s)
    return sessions


def aggregate_sessions(sessions: list[Session]) -> dict[str, Any]:
    """Session list 의 통합 통계 — `activity_summary` MCP tool 의 payload.

    반환 dict 의 모든 값은 JSON-serializable.
    """
    total_events = sum(s.event_count for s in sessions)
    total_tool_calls = sum(s.tool_call_count for s in sessions)
    total_duration = sum(s.duration_seconds or 0.0 for s in sessions)

    tools_used: Counter[str] = Counter()
    for s in sessions:
        tools_used.update(s.tools_used)

    starts = [s.started_at for s in sessions if s.started_at]
    ends = [s.ended_at for s in sessions if s.ended_at]
    oldest = min(starts) if starts else None
    newest = max(ends) if ends else None

    return {
        "total_sessions": len(sessions),
        "total_events": total_events,
        "total_tool_calls": total_tool_calls,
        "total_duration_seconds": total_duration,
        "oldest_session_started_at": oldest.isoformat() if oldest else None,
        "newest_session_ended_at": newest.isoformat() if newest else None,
        "tools_used": dict(tools_used),
    }


def tool_call_ranking(sessions: list[Session], top: int | None = None) -> list[dict[str, Any]]:
    """Tool 별 사용 카운트를 most_common 정렬된 list 로 반환.

    `top` 미지정 시 전체 반환. `tool_call_stats` MCP tool 의 payload.
    """
    total: Counter[str] = Counter()
    for s in sessions:
        total.update(s.tools_used)
    items = total.most_common(top) if top else total.most_common()
    return [{"name": name, "count": count} for name, count in items]
