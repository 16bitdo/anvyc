"""Adapter base interface.

DESIGN.md §11 참고. 모든 도구별 adapter는 이 protocol을 따른다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from anvyc.core.diff import DiffResult
from anvyc.core.inventory import ManagedFile


@dataclass
class Finding:
    severity: str  # "critical" | "high" | "medium" | "low"
    path: Path
    message: str


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

    def validate(self) -> list[Finding]: ...

    def diff(self, source: Path, target: Path) -> DiffResult: ...

    def apply(self, source: Path, target: Path) -> ApplyResult: ...
