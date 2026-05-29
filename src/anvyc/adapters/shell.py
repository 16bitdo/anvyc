"""Shell adapter — `.zshrc`, `.zprofile` 등 zsh dotfile 백업/적용."""
from __future__ import annotations

from pathlib import Path

from anvyc.adapters.base import AdapterMeta, ApplyResult
from anvyc.checks.base import CheckResult
from anvyc.core.diff import DiffResult
from anvyc.core.inventory import ManagedFile

DEFAULT_FILES: tuple[str, ...] = (
    "~/.zshrc",
    "~/.zprofile",
    "~/.zshenv",
    "~/.zlogin",
)


class ShellAdapter:
    name = "shell"
    meta = AdapterMeta(
        name="shell",
        label="Shell (zsh)",
        summary="zsh dotfile (.zshrc / .zprofile 등) 백업·동기화 (shell history 제외)",
        category="shell",
        includes=DEFAULT_FILES,
        excludes=("~/.zsh_history", "~/.zsh_sessions", "~/.zcompdump*"),
        since="v0.1.0",
    )

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
            "~/.zsh_history",
            "~/.zsh_sessions",
            "~/.zcompdump*",
        ]

    def validate(self) -> list[CheckResult]:
        return []

    def diff(self, source: Path, target: Path) -> DiffResult:
        raise NotImplementedError

    def target_hash(self, target: Path) -> str:
        raise NotImplementedError

    def apply(self, source: Path, target: Path) -> ApplyResult:
        raise NotImplementedError
