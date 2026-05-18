"""Git adapter — `.gitconfig`, `.gitignore_global` 등 git 설정 백업/적용.

`.git-credentials`, GPG/SSH key는 기본 제외한다.
"""
from __future__ import annotations

from pathlib import Path

from anvyc.adapters.base import ApplyResult, Finding
from anvyc.core.diff import DiffResult
from anvyc.core.inventory import ManagedFile


class GitAdapter:
    name = "git"

    def detect(self) -> bool:
        return Path("~/.gitconfig").expanduser().exists()

    def collect(self) -> list[ManagedFile]:
        raise NotImplementedError

    def exclude(self) -> list[str]:
        return [
            "~/.git-credentials",
            "~/.ssh/id_rsa",
            "~/.ssh/id_ed25519",
        ]

    def validate(self) -> list[Finding]:
        raise NotImplementedError

    def diff(self, source: Path, target: Path) -> DiffResult:
        raise NotImplementedError

    def apply(self, source: Path, target: Path) -> ApplyResult:
        raise NotImplementedError
