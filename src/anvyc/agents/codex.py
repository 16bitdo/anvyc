"""OpenAI Codex CLI agent adapter (CP-7 stub).

본 어댑터는 Phase A 뼈대의 placeholder. 사용자의 정기 사용 + transcript 위치
모두 미확정이므로 모든 메서드가 NotImplementedError 를 raise 한다.

v5+ 진입 조건은 role-based-ruleset/templates/agents/codex/README.md 참조.
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from anvyc.agents.base import UNIFIED_SCHEMA_VERSION, register_agent
from anvyc.core.activity import Session

_NOT_IMPL_MSG = (
    "Codex adapter 미구현 (CP-7 Phase A stub). "
    "transcript 위치 후보: ~/.codex/sessions/*.jsonl. "
    "v5+ axis 에서 구현 예정 — "
    "role-based-ruleset/templates/agents/codex/README.md 참조."
)


class CodexAdapter:
    name = "codex"
    unified_schema_version = UNIFIED_SCHEMA_VERSION

    def discover_session_files(self) -> Iterator[Path]:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def parse_session(self, path: Path) -> Session | None:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def supports_hooks(self) -> bool:
        return False

    def hook_wire_targets(self) -> list[Path]:
        return []


register_agent(CodexAdapter())
