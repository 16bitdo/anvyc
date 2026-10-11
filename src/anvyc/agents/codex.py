"""Read-only Codex rollout metadata adapter; transcript bodies never leave this module.

Observed local schema: codex-cli 0.159.0 (2026-10-11). Rollout JSONL is not a
stable public API: unknown events are ignored; malformed/missing metadata returns None.
Hooks are a runtime capability, not a guarantee that a configured hook is trusted.
"""
from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from anvyc.agents.base import UNIFIED_SCHEMA_VERSION, register_agent
from anvyc.core.activity import Session


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp if stamp.tzinfo is not None else None
    except ValueError:
        return None


def _count(value: object) -> int:
    return max(0, value) if isinstance(value, int) and not isinstance(value, bool) else 0


def parse_codex_session(path: Path) -> Session | None:
    session: Session | None = None
    token_totals: tuple[int, int, int] = (0, 0, 0)
    pending_events = 0
    seen_calls: set[str] = set()
    last_stamp: datetime | None = None
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue  # includes incomplete tail of an active session
                if not isinstance(event, dict):
                    continue
                payload = event.get("payload")
                if not isinstance(payload, dict):
                    continue
                pending_events += 1
                stamp = _timestamp(event.get("timestamp"))
                if stamp is not None:
                    last_stamp = max(last_stamp, stamp) if last_stamp else stamp
                if event.get("type") == "session_meta" and session is None:
                    sid = payload.get("id") or payload.get("session_id")
                    if not isinstance(sid, str) or not sid:
                        continue
                    session = Session(session_id=sid, source_path=path)
                    cwd = payload.get("cwd")
                    session.cwd = cwd if isinstance(cwd, str) else None
                    git = payload.get("git")
                    branch = git.get("branch") if isinstance(git, dict) else None
                    session.git_branch = branch if isinstance(branch, str) else None
                    session.started_at = _timestamp(payload.get("timestamp")) or stamp
                if session is None:
                    continue
                if event.get("type") == "response_item" and payload.get("type") in {
                    "function_call", "custom_tool_call"
                }:
                    name, call_id = payload.get("name"), payload.get("call_id")
                    if isinstance(name, str) and name:
                        if isinstance(call_id, str) and call_id in seen_calls:
                            continue
                        if isinstance(call_id, str):
                            seen_calls.add(call_id)
                        session.tools_used[name] += 1
                        session.tool_call_count += 1
                usage: Any = None
                if event.get("type") == "event_msg" and payload.get("type") == "token_count":
                    info = payload.get("info")
                    usage = info.get("total_token_usage") if isinstance(info, dict) else None
                elif event.get("type") == "token_usage_record":
                    usage = payload.get("thread_token_usage")
                if isinstance(usage, dict):
                    # Cumulative snapshots repeat. Never add their values together, nor add
                    # reasoning_output_tokens to output_tokens (a component of output).
                    cached = _count(usage.get("cached_input_tokens"))
                    token_totals = (
                        max(token_totals[0], max(0, _count(usage.get("input_tokens")) - cached)),
                        max(token_totals[1], _count(usage.get("output_tokens"))),
                        max(token_totals[2], cached),
                    )
    except (OSError, UnicodeError):
        return None
    if session is not None:
        session.event_count = pending_events
        session.ended_at = last_stamp  # last observed event; does not assert the session ended
        session.tokens_in, session.tokens_out, session.tokens_cache_read = token_totals
        session.cost_usd = None  # subscription usage is not API billing
    return session


class CodexAdapter:
    name = "codex"
    unified_schema_version = UNIFIED_SCHEMA_VERSION

    def discover_session_files(self) -> Iterator[Path]:
        root = codex_home() / "sessions"
        if root.is_dir():
            for path in sorted(root.rglob("*.jsonl")):
                if path.is_file() and not path.is_symlink():
                    yield path

    def parse_session(self, path: Path) -> Session | None:
        return parse_codex_session(path)

    def supports_hooks(self) -> bool:
        return True

    def hook_wire_targets(self) -> list[Path]:
        return [codex_home() / "hooks.json"]


register_agent(CodexAdapter())
