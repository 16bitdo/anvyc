"""tests/unit/test_agents_registry.py — CP-7 Phase A 뼈대 검증.

본 테스트는 anvyc.agents 의 추상화 뼈대만 검증한다 (실제 transcript 파싱
등 동작은 test_activity.py 가 별도로 cover). 검증 항목:

1. AGENT_REGISTRY 에 claude_code / cursor / codex 모두 등록
2. list_agents() 가 정렬된 이름 반환
3. supports_hooks 값 (claude_code=True, 나머지=False)
4. unknown agent lookup → KeyError
5. stub agent 의 discover/parse → NotImplementedError (silent skip 금지)
6. claude_code adapter 가 core.activity 와 호환 (discover_session_files 위임)
7. register_agent 중복 호출 → ValueError
8. AgentAdapter Protocol runtime_checkable
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from anvyc import agents
from anvyc.agents import base as agents_base
from anvyc.agents.base import (
    AGENT_REGISTRY,
    UNIFIED_SCHEMA_VERSION,
    AgentAdapter,
    get_agent,
    list_agents,
    register_agent,
)
from anvyc.core.activity import Session


def test_registry_contains_three_agents() -> None:
    assert set(AGENT_REGISTRY) == {"claude_code", "cursor", "codex"}


def test_list_agents_sorted() -> None:
    assert list_agents() == ["claude_code", "codex", "cursor"]


def test_unified_schema_version_consistent() -> None:
    for name, adapter in AGENT_REGISTRY.items():
        assert adapter.unified_schema_version == UNIFIED_SCHEMA_VERSION, name


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("claude_code", True),
        ("cursor", False),
        ("codex", False),
    ],
)
def test_supports_hooks(name: str, expected: bool) -> None:
    assert get_agent(name).supports_hooks() is expected


def test_get_agent_unknown_raises_key_error() -> None:
    with pytest.raises(KeyError, match="unknown agent"):
        get_agent("notarealagent")


@pytest.mark.parametrize("name", ["codex"])
def test_stub_discover_session_files_raises(name: str) -> None:
    """codex 는 v5 시점 여전히 stub — discover 시 NotImplementedError.

    cursor 는 CP-10 (v5) 에서 impl 전환 — tests/unit/test_agents_cursor.py 가 cover.
    """
    adapter = get_agent(name)
    with pytest.raises(NotImplementedError):
        it = adapter.discover_session_files()
        if isinstance(it, Iterator):
            next(it)


@pytest.mark.parametrize("name", ["codex"])
def test_stub_parse_session_raises(name: str, tmp_path: Path) -> None:
    """codex stub 의 parse_session 도 NotImplementedError (cursor 는 impl)."""
    adapter = get_agent(name)
    with pytest.raises(NotImplementedError):
        adapter.parse_session(tmp_path / "dummy.jsonl")


def test_claude_code_adapter_delegates_discover(monkeypatch: pytest.MonkeyPatch) -> None:
    """claude_code adapter 가 core.activity.iter_session_files 를 위임 호출하는지 확인."""
    from anvyc.core import activity

    sentinel = iter([Path("/sentinel.jsonl")])
    called = {"hit": False}

    def fake_iter(roots: list[Path] | None = None) -> Iterator[Path]:
        called["hit"] = True
        return sentinel

    monkeypatch.setattr(activity, "iter_session_files", fake_iter)
    result = list(get_agent("claude_code").discover_session_files())
    assert called["hit"] is True
    assert result == [Path("/sentinel.jsonl")]


def test_claude_code_hook_wire_targets_returns_list() -> None:
    targets = get_agent("claude_code").hook_wire_targets()
    assert isinstance(targets, list)
    # 모든 entry 는 ~/.claude* 하위. 빈 list 도 허용 (테스트 환경에 claude 없을 수 있음).
    for t in targets:
        assert ".claude" in str(t)


def test_register_agent_duplicate_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # 격리된 registry 로 swap 하여 전역 상태 오염 회피.
    isolated: dict[str, AgentAdapter] = {}
    monkeypatch.setattr(agents_base, "AGENT_REGISTRY", isolated)

    class Dummy:
        name = "dummy"
        unified_schema_version = UNIFIED_SCHEMA_VERSION

        def discover_session_files(self) -> Iterator[Path]:
            return iter([])

        def parse_session(self, path: Path) -> Session | None:
            return None

        def supports_hooks(self) -> bool:
            return False

        def hook_wire_targets(self) -> list[Path]:
            return []

    register_agent(Dummy())
    with pytest.raises(ValueError, match="already registered"):
        register_agent(Dummy())


def test_adapter_protocol_runtime_checkable() -> None:
    for adapter in AGENT_REGISTRY.values():
        assert isinstance(adapter, AgentAdapter)


def test_package_reexports() -> None:
    """anvyc.agents 가 base 의 핵심 심볼을 re-export."""
    assert agents.AGENT_REGISTRY is AGENT_REGISTRY
    assert agents.get_agent is get_agent
    assert agents.list_agents is list_agents
    assert agents.register_agent is register_agent
    assert agents.UNIFIED_SCHEMA_VERSION == UNIFIED_SCHEMA_VERSION


# --- CP-7 Phase B: collect_sessions agent dispatch ---


def test_collect_sessions_unknown_agent_raises_key_error() -> None:
    from anvyc.core.activity import collect_sessions

    with pytest.raises(KeyError, match="unknown agent"):
        collect_sessions(agent="notarealagent")


@pytest.mark.parametrize("name", ["codex"])
def test_collect_sessions_stub_agent_raises_not_implemented(name: str) -> None:
    """v5 시점 codex 만 stub — cursor 는 CP-10 으로 impl 전환."""
    from anvyc.core.activity import collect_sessions

    with pytest.raises(NotImplementedError):
        collect_sessions(agent=name)


def test_collect_sessions_roots_and_agent_mutually_exclusive(tmp_path: Path) -> None:
    from anvyc.core.activity import collect_sessions

    with pytest.raises(ValueError, match="함께 지정할 수 없습니다"):
        collect_sessions(roots=[tmp_path], agent="claude_code")


def test_collect_sessions_union_skips_stub_silently(monkeypatch: pytest.MonkeyPatch) -> None:
    """agent=None (union) 모드는 stub adapter 의 NotImplementedError 를 silent skip.

    v5 이후: claude_code (impl) + cursor (impl, CP-10) + codex (stub) — 모든
    adapter 의 실 데이터 source 를 monkeypatch 로 격리한 빈 환경에서 union
    결과가 empty 인지 검증. codex 의 NotImplementedError 도 silent skip 보장.
    """
    from anvyc.agents import cursor as cursor_mod
    from anvyc.core import activity as activity_mod

    monkeypatch.setattr(activity_mod, "iter_session_files", lambda roots=None: iter([]))
    # cursor 도 격리 — 실머신 SQLite 누설 차단 (v5 CP-10 후 impl 됨).
    monkeypatch.setattr(cursor_mod, "discover_cursor_sqlites", lambda user_dir=None: [])
    result = activity_mod.collect_sessions()
    assert result == []


def test_collect_sessions_claude_code_explicit_uses_adapter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """agent='claude_code' 명시 시 adapter 의 discover/parse 가 호출되는지 검증."""
    from anvyc.core import activity as activity_mod

    fake_path = tmp_path / "fake.jsonl"
    fake_path.write_text("{}", encoding="utf-8")

    # claude_code adapter 의 discover_session_files 는 activity.iter_session_files 위임.
    monkeypatch.setattr(activity_mod, "iter_session_files", lambda roots=None: iter([fake_path]))
    monkeypatch.setattr(activity_mod, "parse_session", lambda p: None)

    result = activity_mod.collect_sessions(agent="claude_code")
    assert result == []  # parse_session 가 None 반환 → 빈 list
