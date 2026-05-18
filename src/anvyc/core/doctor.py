"""Doctor orchestrator.

DESIGN.md §27 참고. 등록된 Check 들을 실행하고 결과를 형식화한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from anvyc.checks.base import CheckContext, CheckResult, Severity


@dataclass
class DoctorReport:
    results: list[CheckResult] = field(default_factory=list)

    def by_severity(self) -> dict[Severity, list[CheckResult]]:
        out: dict[Severity, list[CheckResult]] = {s: [] for s in Severity}
        for r in self.results:
            out[r.severity].append(r)
        return out

    def has_blocking(self) -> bool:
        return any(r.severity.is_blocking for r in self.results)


def run_doctor(
    ctx: CheckContext,
    *,
    only: list[str] | None = None,
    skip: list[str] | None = None,
) -> DoctorReport:
    """등록된 Check 들을 실행한다 (MVP TODO)."""
    raise NotImplementedError
