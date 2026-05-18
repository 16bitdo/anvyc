"""Secret scanner — 파일 또는 디렉터리에서 패턴 탐지."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from anvyc.security.patterns import OP_REFERENCE_RE, PATTERNS

_MAX_SCAN_BYTES = 10_485_760  # 10 MiB — 그 이상은 binary 가능성 + 비용 회피


@dataclass
class ScanFinding:
    path: Path
    pattern: str
    severity: str
    line_number: int
    excerpt: str


def scan_file(path: Path) -> list[ScanFinding]:
    """단일 파일에 대해 패턴 매칭을 수행한다.

    op:// reference (1Password Secret Reference) 가 같은 라인에 있으면 해당 라인의
    다른 secret 패턴 매칭을 "low" 로 강등한다 (DESIGN.md §30.2).
    """
    findings: list[ScanFinding] = []
    try:
        if not path.is_file():
            return []
        if path.stat().st_size > _MAX_SCAN_BYTES:
            return []
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for line_num, line in enumerate(f, start=1):
                has_op_ref = OP_REFERENCE_RE.search(line) is not None
                for pat in PATTERNS:
                    m = pat.regex.search(line)
                    if not m:
                        continue
                    severity = pat.severity
                    if has_op_ref:
                        # op:// 가 같은 라인에 있으면 placeholder 의 일부일 가능성 — 강등.
                        # 단 private_key 같이 multiline 패턴은 단일 라인에서 op:// 와 공존할
                        # 가능성이 없어 영향이 없다.
                        severity = "low"
                    findings.append(
                        ScanFinding(
                            path=path,
                            pattern=pat.name,
                            severity=severity,
                            line_number=line_num,
                            excerpt=line.strip()[:120],
                        )
                    )
    except (OSError, PermissionError):
        pass
    return findings


def extract_op_references(path: Path) -> list[tuple[int, str]]:
    """파일 안의 op:// reference 들을 (line_number, uri) 튜플 목록으로 반환한다.

    P5.2 doctor check (op-references-valid) 에서 사용.
    """
    refs: list[tuple[int, str]] = []
    try:
        if not path.is_file():
            return []
        if path.stat().st_size > _MAX_SCAN_BYTES:
            return []
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for line_num, line in enumerate(f, start=1):
                for m in OP_REFERENCE_RE.finditer(line):
                    refs.append((line_num, m.group(0)))
    except (OSError, PermissionError):
        pass
    return refs


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


__all__ = [
    "ScanFinding",
    "scan_file",
    "scan_paths",
    "extract_op_references",
    "PATTERNS",
    "OP_REFERENCE_RE",
]
