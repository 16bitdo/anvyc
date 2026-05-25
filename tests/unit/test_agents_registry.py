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


@pytest.mark.parametrize("name", ["cursor", "codex"])
def test_stub_discover_session_files_raises(name: str) -> None:
    adapter = get_agent(name)
    with pytest.raises(NotImplementedError):
        # stub 의 호출 자체가 raise 일 수도, generator 진입 시 raise 일 수도.
        # 두 경우 모두 with 안에서 catch 되도록 호출도 안쪽에 둔다.
        it = adapter.discover_session_files()
        if isinstance(it, Iterator):
            next(it)


@pytest.mark.parametrize("name", ["cursor", "codex"])
def test_stub_parse_session_raises(name: str, tmp_path: Path) -> None:
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
