"""Synthetic rollout fixtures: privacy, cumulative usage, active tails and isolation."""
import json
from pathlib import Path

import pytest

from anvyc.agents.codex import CodexAdapter, parse_codex_session


def test_rollout_metadata_and_cumulative_usage(tmp_path: Path) -> None:
    path = tmp_path / "rollout.jsonl"
    rows = [
        {"type": "session_meta", "timestamp": "2026-10-11T00:00:00Z", "payload": {
            "id": "session-1", "cwd": "/test/project", "git": {"branch": "codex/test"},
            "base_instructions": "PRIVATE INSTRUCTIONS"}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command",
                                              "call_id": "call-1", "arguments": "PRIVATE COMMAND"}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command",
                                              "call_id": "call-1"}},
        {"type": "event_msg", "timestamp": "2026-10-11T00:01:00Z", "payload": {
            "type": "token_count", "info": {"total_token_usage": {
                "input_tokens": 100, "cached_input_tokens": 30, "output_tokens": 20,
                "reasoning_output_tokens": 5}}}},
        {"type": "token_usage_record", "payload": {"thread_token_usage": {
            "input_tokens": 100, "cached_input_tokens": 30, "output_tokens": 20}}},
        {"type": "response_item", "payload": {"type": "message", "content": "PRIVATE TEXT"}},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + '\n{"partial":')
    session = parse_codex_session(path)
    assert session is not None
    assert session.session_id == "session-1"
    assert session.git_branch == "codex/test"
    assert session.tool_call_count == 1
    assert session.tools_used == {"exec_command": 1}
    assert (session.tokens_in, session.tokens_cache_read, session.tokens_out) == (70, 30, 20)
    assert session.cost_usd is None
    assert session.duration_seconds == 60
    assert "PRIVATE" not in json.dumps(session.to_dict())


def test_discovery_respects_codex_home_and_nested_dates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    path = tmp_path / "sessions/2026/10/11/rollout.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("{}")
    (path.parent / "linked.jsonl").symlink_to(path)
    assert list(CodexAdapter().discover_session_files()) == [path]
    assert CodexAdapter().hook_wire_targets() == [tmp_path / "hooks.json"]


def test_unknown_or_corrupt_log_does_not_become_session(tmp_path: Path) -> None:
    path = tmp_path / "unknown.jsonl"
    path.write_text('null\n[]\n{"payload": []}\ninvalid\n')
    assert parse_codex_session(path) is None
