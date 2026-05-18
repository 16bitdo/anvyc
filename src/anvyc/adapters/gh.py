"""GitHub CLI adapter — `~/.config/gh/config.yml`만 백업. hosts.yml(token 포함)은 기본 제외."""
from __future__ import annotations

from pathlib import Path

from anvyc.adapters.base import ApplyResult, Finding
from anvyc.core.diff import DiffResult
from anvyc.core.inventory import ManagedFile


class GhAdapter:
    name = "gh"

    def detect(self) -> bool:
        return Path("~/.config/gh/config.yml").expanduser().exists()

    def collect(self) -> list[ManagedFile]:
        raise NotImplementedError

    def exclude(self) -> list[str]:
        return [
            "~/.config/gh/hosts.yml",
        ]

    def validate(self) -> list[Finding]:
        raise NotImplementedError

    def diff(self, source: Path, target: Path) -> DiffResult:
        raise NotImplementedError

    def apply(self, source: Path, target: Path) -> ApplyResult:
        raise NotImplementedError
