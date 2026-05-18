"""Secret scanner — 파일 또는 디렉터리에서 패턴 탐지."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from anvyc.security.patterns import PATTERNS


@dataclass
class ScanFinding:
    path: Path
    pattern: str
    severity: str
    line_number: int
    excerpt: str


def scan_file(path: Path) -> list[ScanFinding]:
    """단일 파일에 대해 패턴 매칭을 수행한다 (MVP TODO)."""
    raise NotImplementedError


def scan_paths(paths: list[Path]) -> list[ScanFinding]:
    """여러 경로(파일/디렉터리)에 대해 일괄 스캔."""
    raise NotImplementedError


__all__ = ["ScanFinding", "scan_file", "scan_paths", "PATTERNS"]
