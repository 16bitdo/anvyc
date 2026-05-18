"""Shell adapter — `.zshrc`, `.zprofile` 등 zsh dotfile 백업/적용."""
from __future__ import annotations

from pathlib import Path

from anvyc.adapters.base import ApplyResult, Finding
from anvyc.core.diff import DiffResult
from anvyc.core.inventory import ManagedFile


class ShellAdapter:
    name = "shell"

    def detect(self) -> bool:
        return Path("~/.zshrc").expanduser().exists()

    def collect(self) -> list[ManagedFile]:
        raise NotImplementedError

    def exclude(self) -> list[str]:
        return [
            "~/.zsh_history",
            "~/.zsh_sessions",
        ]

    def validate(self) -> list[Finding]:
        raise NotImplementedError

    def diff(self, source: Path, target: Path) -> DiffResult:
        raise NotImplementedError

    def apply(self, source: Path, target: Path) -> ApplyResult:
        raise NotImplementedError
