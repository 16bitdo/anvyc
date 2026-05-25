"""Claude Code agent adapter (CP-7, Control Plane v4).

기존 `anvyc/core/activity.py` 의 transcript 수집 로직을 위임하는 thin wrapper.
본 PR (Phase A 뼈대) 에서는 activity.py 본문을 수정하지 않고 위임만 추가한다.
activity.py 의 registry-기반 전환은 후속 PR (CP-7 Phase B) 의 책임.
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from anvyc.agents.base import UNIFIED_SCHEMA_VERSION, register_agent
from anvyc.core import activity


class ClaudeCodeAdapter:
    """`~/.claude*/projects/*/*.jsonl` (Claude Code session transcript) 어댑터.

    멀티 계정 환경 (`~/.claude`, `~/.claude-edward`, `~/.claude-jklee`) 을
    자동으로 모두 스캔한다. activity.discover_session_roots() 의 기본 동작과
    동일.
    """

    name = "claude_code"
    unified_schema_version = UNIFIED_SCHEMA_VERSION

    def discover_session_files(self) -> Iterator[Path]:
        return activity.iter_session_files()

    def parse_session(self, path: Path) -> activity.Session | None:
        return activity.parse_session(path)

    def supports_hooks(self) -> bool:
        return True

    def hook_wire_targets(self) -> list[Path]:
        """모든 `~/.claude*` 프로필의 settings.json 을 반환."""
        home = Path.home()
        targets: list[Path] = []
        for entry in sorted(home.glob(".claude*")):
            settings = entry / "settings.json"
            if settings.exists() or entry.is_dir():
                targets.append(settings)
        return targets


register_agent(ClaudeCodeAdapter())
