"""shell prompt adapter — starship / powerlevel10k 설정 파일 백업.

starship(`~/.config/starship.toml`)·powerlevel10k(`~/.p10k.zsh`) 의 prompt
설정 파일을 백업/동기화한다. 두 도구는 동일 도메인(shell prompt 설정)이고
사용자는 보통 하나만 쓰므로 단일 adapter 로 묶는다 — 존재하는 파일만 collect.

주의: p10k 의 instant-prompt 캐시(`~/.cache/p10k-*`)는 재생성 가능한 머신
로컬 파일이므로 추적하지 않는다 — DEFAULT_FILES 가 설정 파일 2개만 명시한다.
"""
from __future__ import annotations

from pathlib import Path

from anvyc.adapters.base import AdapterMeta, ApplyResult
from anvyc.checks.base import CheckResult
from anvyc.core.diff import DiffResult
from anvyc.core.inventory import ManagedFile

DEFAULT_FILES: tuple[str, ...] = (
    "~/.config/starship.toml",
    "~/.p10k.zsh",
)


class ShellPromptAdapter:
    name = "shell_prompt"
    meta = AdapterMeta(
        name="shell_prompt",
        label="Shell Prompt",
        summary="starship / powerlevel10k prompt 설정 백업 (instant-prompt 캐시 미수집)",
        category="shell",
        includes=DEFAULT_FILES,
        excludes=(),
        since="v0.13.0",
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
        return []

    def validate(self) -> list[CheckResult]:
        return []

    def diff(self, source: Path, target: Path) -> DiffResult:
        raise NotImplementedError

    def target_hash(self, target: Path) -> str:
        raise NotImplementedError

    def apply(self, source: Path, target: Path) -> ApplyResult:
        raise NotImplementedError
