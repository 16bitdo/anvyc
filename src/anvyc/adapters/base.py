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


# AdapterMeta.category 허용값 — list/configure/wizard 의 그룹핑 키.
# drift 방지: 테스트(test_adapter_meta)가 meta.category 가 이 집합에 속하는지 강제한다.
ADAPTER_CATEGORIES: frozenset[str] = frozenset(
    {"shell", "vcs", "cloud", "iac", "ide", "ai-agent", "terminal", "dev-env"}
)

# 아직 미지원 — 향후 adapter 후보. `tools list` footer 의 단일 SoT (과거 cli.py
# 하드코딩 대체). 신규 adapter 후보는 여기만 갱신하면 footer 가 자동 반영된다.
PLANNED_ADAPTERS: tuple[str, ...] = ("vscode", "helix", "neovim")


@dataclass(frozen=True)
class AdapterMeta:
    """도구별 *정적* 메타데이터 — tools list / configure / wizard / MCP / README 의 단일 SoT.

    런타임 파생값(enabled / detected / file·secret count)은 담지 않는다. 인스턴스
    상태·secret 과 무관한 '설명용' 정보만 보유한다. 각 adapter 가 `name` 처럼 클래스
    속성으로 노출하므로 인스턴스 생성 없이 `cls.meta` 로 접근할 수 있다.

    - file-based adapter 는 `includes=DEFAULT_FILES` 로 모듈 상수를 *동일 객체* 참조해
      drift 를 원천 차단한다.
    - `excludes` 는 사용자에게 보여줄 '기본 제외' 표시용 목록이다. 경로형 adapter 는
      실제 `exclude()` 의 부분집합이어야 한다(테스트가 강제 — 거짓 표시 방지).
    """

    name: str
    label: str
    summary: str
    category: str
    includes: tuple[str, ...]
    excludes: tuple[str, ...]
    default_enabled: bool = True
    config_kind: str = "files"  # "files" | "structured"
    since: str = ""


@runtime_checkable
class Adapter(Protocol):
    name: str
    meta: AdapterMeta

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
