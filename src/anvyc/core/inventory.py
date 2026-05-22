"""Source/target state inventory.

각 adapter 가 보고한 ManagedFile 목록을 통합하여 상태 inventory 를 만든다.

ManagedFile 의 source/target 의미:
  source_path  현재 머신에서 실제 읽어올 절대 경로 (~ 확장 완료)
  target_path  복원 시 도달해야 할 canonical 경로 (~/ 형식 유지, 머신 독립)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anvyc.adapters.base import Adapter


@dataclass
class ManagedFile:
    """adapter 가 관리하는 단일 파일 단위.

    relpath          backup/<tool>/ 아래에서의 상대 경로. 비워두면 source_path.name 으로 채워진다.
                     디렉터리 재귀 수집 시 nested 경로를 보존하기 위해 사용 (예: 'hooks/script.sh').
    symlink_target   None 이 아니면 이 entry 는 symlink. backup 은 콘텐츠를 복사하지 않고
                     metadata.json 에 symlinkTarget 만 기록. apply 는 os.symlink 로 재생성.
    """

    tool: str
    source_path: Path
    target_path: Path
    mode: int = 0o600
    sha256: str | None = None
    relpath: str = ""
    symlink_target: str | None = None

    def __post_init__(self) -> None:
        if not self.relpath:
            self.relpath = self.source_path.name


@dataclass
class Inventory:
    """전체 관리 대상 파일 목록."""

    files: list[ManagedFile] = field(default_factory=list)

    def by_tool(self, tool: str) -> list[ManagedFile]:
        return [f for f in self.files if f.tool == tool]


def build_source_inventory(adapters: list[Adapter]) -> Inventory:
    """detect() 가 True 인 adapter 들의 collect() 를 합산한 inventory."""
    inv = Inventory()
    for ad in adapters:
        try:
            if not ad.detect():
                continue
            inv.files.extend(ad.collect())
        except NotImplementedError:
            continue
    return inv


def build_target_inventory() -> Inventory:
    """backup repo 에서 적용 대상 파일 목록을 산출한다 (MVP TODO)."""
    raise NotImplementedError
