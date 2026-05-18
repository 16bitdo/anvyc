"""Source/target state inventory.

각 adapter가 보고한 ManagedFile 목록을 통합하여 상태 inventory를 만든다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ManagedFile:
    """adapter가 관리하는 단일 파일 단위."""

    tool: str
    source_path: Path
    target_path: Path
    mode: int = 0o600
    sha256: str | None = None


@dataclass
class Inventory:
    """전체 관리 대상 파일 목록."""

    files: list[ManagedFile] = field(default_factory=list)

    def by_tool(self, tool: str) -> list[ManagedFile]:
        return [f for f in self.files if f.tool == tool]


def build_source_inventory() -> Inventory:
    """현재 환경에서 backup 대상 파일 목록을 산출한다 (MVP TODO)."""
    raise NotImplementedError


def build_target_inventory() -> Inventory:
    """backup repo에서 적용 대상 파일 목록을 산출한다 (MVP TODO)."""
    raise NotImplementedError
