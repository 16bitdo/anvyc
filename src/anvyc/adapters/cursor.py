"""Cursor IDE adapter.

포함: settings.json, keybindings.json, snippets/, ~/.cursor/rules, ~/.cursor/skills, mcp.json
제외: workspaceStorage, History, globalStorage 전체
"""
from __future__ import annotations

from pathlib import Path

from anvyc.adapters.base import ApplyResult, Finding
from anvyc.core.diff import DiffResult
from anvyc.core.inventory import ManagedFile

USER_DIR = Path("~/Library/Application Support/Cursor/User").expanduser()


class CursorAdapter:
    name = "cursor"

    def detect(self) -> bool:
        return USER_DIR.exists()

    def collect(self) -> list[ManagedFile]:
        raise NotImplementedError

    def exclude(self) -> list[str]:
        return [
            "~/Library/Application Support/Cursor/User/workspaceStorage",
            "~/Library/Application Support/Cursor/User/History",
            "~/Library/Application Support/Cursor/User/globalStorage",
            "~/Library/Application Support/Cursor/logs",
            "~/Library/Application Support/Cursor/Cache",
        ]

    def validate(self) -> list[Finding]:
        raise NotImplementedError

    def diff(self, source: Path, target: Path) -> DiffResult:
        raise NotImplementedError

    def apply(self, source: Path, target: Path) -> ApplyResult:
        raise NotImplementedError
