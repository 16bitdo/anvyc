"""Secret scanner — 파일 또는 디렉터리에서 패턴 탐지."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from anvyc.security.patterns import PATTERNS

_MAX_SCAN_BYTES = 10_485_760  # 10 MiB — 그 이상은 binary 가능성 + 비용 회피


@dataclass
class ScanFinding:
    path: Path
    pattern: str
    severity: str
    line_number: int
    excerpt: str


def scan_file(path: Path) -> list[ScanFinding]:
    """단일 파일에 대해 패턴 매칭을 수행한다."""
    findings: list[ScanFinding] = []
    try:
        if not path.is_file():
            return []
        if path.stat().st_size > _MAX_SCAN_BYTES:
            return []
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for line_num, line in enumerate(f, start=1):
                for pat in PATTERNS:
                    m = pat.regex.search(line)
                    if not m:
                        continue
                    findings.append(
                        ScanFinding(
                            path=path,
                            pattern=pat.name,
                            severity=pat.severity,
                            line_number=line_num,
                            excerpt=line.strip()[:120],
                        )
                    )
    except (OSError, PermissionError):
        pass
    return findings


def scan_paths(paths: list[Path]) -> list[ScanFinding]:
    """여러 경로(파일/디렉터리)에 대해 일괄 스캔. 디렉터리는 재귀."""
    results: list[ScanFinding] = []
    for p in paths:
        if p.is_file():
            results.extend(scan_file(p))
        elif p.is_dir():
            for child in p.rglob("*"):
                if child.is_file():
                    results.extend(scan_file(child))
    return results


__all__ = ["ScanFinding", "scan_file", "scan_paths", "PATTERNS"]
