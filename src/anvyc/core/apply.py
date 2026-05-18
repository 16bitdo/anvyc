"""Apply engine.

12.2 절차:
1) anvyc.yaml → 2) source/target inventory → 3) diff → 4) secret scan
5) local backup → 6) 파일 적용 → 7) 권한 보정 → 8) hash 검증 → 9) apply report
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ApplyResult:
    applied: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)


def run_apply(root: Path, *, dry_run: bool = False) -> ApplyResult:
    """전체 apply 워크플로를 실행한다 (MVP TODO)."""
    raise NotImplementedError
