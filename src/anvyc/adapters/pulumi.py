"""Pulumi adapter — `~/.pulumi/config.json`만 백업. credentials.json은 기본 제외."""
from __future__ import annotations

from pathlib import Path

from anvyc.adapters.base import ApplyResult, Finding
from anvyc.core.diff import DiffResult
from anvyc.core.inventory import ManagedFile


class PulumiAdapter:
    name = "pulumi"

    def detect(self) -> bool:
        return Path("~/.pulumi").expanduser().exists()

    def collect(self) -> list[ManagedFile]:
        raise NotImplementedError

    def exclude(self) -> list[str]:
        return [
            "~/.pulumi/credentials.json",
            "~/.pulumi/access_tokens",
        ]

    def validate(self) -> list[Finding]:
        raise NotImplementedError

    def diff(self, source: Path, target: Path) -> DiffResult:
        raise NotImplementedError

    def apply(self, source: Path, target: Path) -> ApplyResult:
        raise NotImplementedError
