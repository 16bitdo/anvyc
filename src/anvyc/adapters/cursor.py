"""Cursor IDE adapter.

DESIGN.md §15 정책 반영. Cursor 설정은 3-layer로 다룬다.

- Layer A (~/.cursor/)          : rules / skills / mcp / plugins
- Layer B (Library/.../Cursor)  : settings / keybindings / snippets / profiles
- Layer C (project-local)        : <repo>/.cursor (opt-in)
"""
from __future__ import annotations

from pathlib import Path

from anvyc.adapters.base import ApplyResult, Finding
from anvyc.core.diff import DiffResult
from anvyc.core.inventory import ManagedFile

USER_HOME = Path("~").expanduser()
CURSOR_GLOBAL_DIR = USER_HOME / ".cursor"
CURSOR_USER_DIR = USER_HOME / "Library" / "Application Support" / "Cursor" / "User"

LAYER_A_INCLUDE: tuple[str, ...] = (
    "~/.cursor/rules",
    "~/.cursor/skills",
    "~/.cursor/skills-cursor",
    "~/.cursor/mcp.json",
    "~/.cursor/plugins/local",
    "~/.cursor/plans",
)

LAYER_A_EXCLUDE: tuple[str, ...] = (
    "~/.cursor/cli-config.json",
    "~/.cursor/argv.json",
    "~/.cursor/ide_state.json",
    "~/.cursor/extensions",
    "~/.cursor/projects",
    "~/.cursor/workers",
    "~/.cursor/ai-tracking",
    "~/.cursor/chats",
    "~/.cursor/plugins/cache",
    "~/.cursor/prompt_history.json",
    "~/.cursor/rules.bak-*",
)

LAYER_B_INCLUDE: tuple[str, ...] = (
    "~/Library/Application Support/Cursor/User/settings.json",
    "~/Library/Application Support/Cursor/User/keybindings.json",
    "~/Library/Application Support/Cursor/User/snippets",
    "~/Library/Application Support/Cursor/User/profiles",
)

LAYER_B_EXCLUDE: tuple[str, ...] = (
    "~/Library/Application Support/Cursor/User/workspaceStorage",
    "~/Library/Application Support/Cursor/User/History",
    "~/Library/Application Support/Cursor/User/globalStorage",
    "~/Library/Application Support/Cursor/logs",
    "~/Library/Application Support/Cursor/Cache",
)


class CursorAdapter:
    name = "cursor"

    def detect(self) -> bool:
        return CURSOR_USER_DIR.exists() or CURSOR_GLOBAL_DIR.exists()

    def collect(self) -> list[ManagedFile]:
        raise NotImplementedError

    def exclude(self) -> list[str]:
        return [*LAYER_A_EXCLUDE, *LAYER_B_EXCLUDE]

    def validate(self) -> list[Finding]:
        raise NotImplementedError

    def diff(self, source: Path, target: Path) -> DiffResult:
        raise NotImplementedError

    def apply(self, source: Path, target: Path) -> ApplyResult:
        raise NotImplementedError
