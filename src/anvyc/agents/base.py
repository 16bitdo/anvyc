"""AgentAdapter Protocol + AGENT_REGISTRY (CP-7, Control Plane v4).

DESIGN.md §7.7 (role-based-ruleset) 의 agent agnosticism 원칙을 구현하는 SoT.
어떤 layer 도 특정 agent 본문에 의존하지 않는다 — observability / hook /
schema 는 모두 본 registry 를 거친다.

신규 agent 추가 절차:
1. role-based-ruleset/templates/agents/_schema.yaml 에 entry 추가
2. role-based-ruleset/templates/agents/<name>/ 디렉토리 + README
3. anvyc/agents/<name>.py 작성 (AgentAdapter Protocol 구현)
4. 본 모듈의 import 부에 추가는 불필요 — `anvyc/agents/__init__.py` 가
   side-effect import 로 자동 수집한다.
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, runtime_checkable

from anvyc.core.activity import Session

UNIFIED_SCHEMA_VERSION = 1


@runtime_checkable
class AgentAdapter(Protocol):
    """모든 agent adapter 가 구현해야 하는 공통 인터페이스.

    `discover_session_files()` / `parse_session()` 은 read-only observability
    의 최소 표면. 미지원 agent 는 NotImplementedError 를 명시적으로 raise 하여
    CLI/MCP 레벨에서 사용자 메시지로 변환되도록 한다 (silent skip 금지).
    """

    name: str
    unified_schema_version: int

    def discover_session_files(self) -> Iterator[Path]:
        """본 agent 의 transcript / session log 파일을 yield."""
        ...

    def parse_session(self, path: Path) -> Session | None:
        """단일 session 파일을 정규화된 Session dataclass 로 변환."""
        ...

    def supports_hooks(self) -> bool:
        """PreToolUse 동등 hook 차단 인터페이스 보유 여부."""
        ...

    def hook_wire_targets(self) -> list[Path]:
        """hook 을 wire 할 대상 파일 목록 (예: ~/.<profile>/settings.json)."""
        ...


AGENT_REGISTRY: dict[str, AgentAdapter] = {}


def register_agent(adapter: AgentAdapter) -> None:
    """Adapter 를 registry 에 등록. 중복 이름은 ValueError."""
    if adapter.name in AGENT_REGISTRY:
        raise ValueError(f"agent already registered: {adapter.name}")
    AGENT_REGISTRY[adapter.name] = adapter


def get_agent(name: str) -> AgentAdapter:
    """이름으로 adapter lookup. 미등록은 KeyError."""
    if name not in AGENT_REGISTRY:
        raise KeyError(
            f"unknown agent: {name!r} (등록된 agent: {sorted(AGENT_REGISTRY)})"
        )
    return AGENT_REGISTRY[name]


def list_agents() -> list[str]:
    """등록된 agent 이름 목록 (정렬)."""
    return sorted(AGENT_REGISTRY)
