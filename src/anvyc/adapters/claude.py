"""Claude Code adapter.

포함: settings.json, hooks/, plugins/, CLAUDE.md template, project instructions
제외: sessions, tokens, conversation history, cache, logs
"""
from __future__ import annotations

from pathlib import Path

from anvyc.adapters.base import ApplyResult
from anvyc.checks.base import CheckResult
from anvyc.core.diff import DiffResult
from anvyc.core.inventory import ManagedFile


class ClaudeAdapter:
    name = "claude"

    def detect(self) -> bool:
        return Path("~/.claude").expanduser().exists()

    def collect(self) -> list[ManagedFile]:
        raise NotImplementedError

    def exclude(self) -> list[str]:
        return [
            "~/.claude/sessions",
            "~/.claude/tokens",
            "~/.claude/cache",
            "~/.claude/logs",
            "~/.claude/conversations",
        ]

    def validate(self) -> list[CheckResult]:
        raise NotImplementedError

    def diff(self, source: Path, target: Path) -> DiffResult:
        raise NotImplementedError

    def apply(self, source: Path, target: Path) -> ApplyResult:
        raise NotImplementedError
