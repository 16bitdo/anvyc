"""Adapter base interface.

DESIGN.md §11 참고. 모든 도구별 adapter 는 이 protocol 을 따른다.
validate() 결과는 checks.base.CheckResult 로 통일한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from anvyc.checks.base import CheckResult
from anvyc.core.diff import DiffResult
from anvyc.core.inventory import ManagedFile


@dataclass
class ApplyResult:
    target: Path
    changed: bool
    backed_up: Path | None = None
    notes: list[str] = field(default_factory=list)


@runtime_checkable
class Adapter(Protocol):
    name: str

    def detect(self) -> bool: ...

    def collect(self) -> list[ManagedFile]: ...

    def exclude(self) -> list[str]: ...

    def validate(self) -> list[CheckResult]: ...

    def diff(self, source: Path, target: Path) -> DiffResult: ...

    def apply(self, source: Path, target: Path) -> ApplyResult: ...

    def target_hash(self, target: Path) -> str:
        """target 의 hash 를 계산. 단순 file copy adapter 는 sha256_file 로 충분하지만,
        iTerm2 처럼 backup 이 target 의 일부만 추출하는 경우 NotImplementedError 대신
        같은 추출 + 직렬화 로직으로 hash 를 계산해야 정확한 unchanged/modified 판정 가능.
        status/apply 의 dispatch 가 NotImplementedError 시 sha256_file 로 폴백한다.
        """
        ...
