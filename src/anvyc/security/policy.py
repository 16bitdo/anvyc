"""Scan 결과에 대한 정책 평가.

DESIGN.md §13.2:
  critical / high  → 중단
  medium           → 경고 + --force 필요
  low              → 정보 로그
"""
from __future__ import annotations

from dataclasses import dataclass

from anvyc.security.scanner import ScanFinding


@dataclass
class PolicyDecision:
    block: bool
    warn: bool
    reasons: list[str]


def evaluate(findings: list[ScanFinding], *, force: bool = False) -> PolicyDecision:
    """findings 목록을 정책에 비추어 차단/경고 여부를 결정한다."""
    reasons: list[str] = []
    block = False
    warn = False

    for f in findings:
        if f.severity in ("critical", "high"):
            block = True
            reasons.append(f"{f.severity.upper()}: {f.pattern} at {f.path}:{f.line_number}")
        elif f.severity == "medium":
            warn = True
            reasons.append(f"MEDIUM: {f.pattern} at {f.path}:{f.line_number}")
            if not force:
                block = True

    return PolicyDecision(block=block, warn=warn, reasons=reasons)
