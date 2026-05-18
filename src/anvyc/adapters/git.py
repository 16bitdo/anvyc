"""Git adapter — `.gitconfig`, `.gitignore_global` 등 git 설정 백업/적용.

`.git-credentials`, GPG/SSH key는 기본 제외한다.
"""
from __future__ import annotations

from pathlib import Path

from anvyc.adapters.base import ApplyResult
from anvyc.checks.base import CheckResult
from anvyc.core.diff import DiffResult
from anvyc.core.inventory import ManagedFile

DEFAULT_FILES: tuple[str, ...] = (
    "~/.gitconfig",
    "~/.gitignore_global",
)


class GitAdapter:
    name = "git"

    def __init__(self, files: tuple[str, ...] | None = None) -> None:
        self._files = files if files is not None else DEFAULT_FILES

    def detect(self) -> bool:
        return any(Path(f).expanduser().exists() for f in self._files)

    def collect(self) -> list[ManagedFile]:
        out: list[ManagedFile] = []
        for canonical in self._files:
            src = Path(canonical).expanduser()
            if not src.is_file():
                continue
            out.append(
                ManagedFile(
                    tool=self.name,
                    source_path=src,
                    target_path=Path(canonical),
                    mode=src.stat().st_mode & 0o777,
                )
            )
        return out

    def exclude(self) -> list[str]:
        return [
            "~/.git-credentials",
            "~/.ssh/id_rsa",
            "~/.ssh/id_ed25519",
            "~/.ssh/id_ed25519-*",
        ]

    def validate(self) -> list[CheckResult]:
        return []

    def diff(self, source: Path, target: Path) -> DiffResult:
        raise NotImplementedError

    def apply(self, source: Path, target: Path) -> ApplyResult:
        raise NotImplementedError
