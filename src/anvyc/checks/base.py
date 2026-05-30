"""Doctor check 공통 타입.

DESIGN.md §27.2 참고.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class Severity(StrEnum):
    INFO = "info"
    INFO_ALIASED = "info-aliased"
    WARNING = "warning"  # generic warning (cross-user 외 다른 check 용)
    WARNING_FOREIGN = "warning-foreign"
    WARNING_DANGLING = "warning-dangling"
    CRITICAL = "critical"

    @property
    def is_blocking(self) -> bool:
        """strict 모드에서 exit 1 처리 대상."""
        return self in (
            Severity.WARNING,
            Severity.WARNING_FOREIGN,
            Severity.WARNING_DANGLING,
            Severity.CRITICAL,
        )


@dataclass
class CheckResult:
    check_name: str
    severity: Severity
    message: str
    location: Path | None = None
    line: int | None = None
    suggestion: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "check_name": self.check_name,
            "severity": self.severity.value,
            "message": self.message,
            "location": str(self.location) if self.location else None,
            "line": self.line,
            "suggestion": self.suggestion,
        }


@dataclass
class CheckContext:
    """check 실행에 필요한 환경 정보."""

    current_user: str = ""
    known_user_aliases: dict[str, str] = field(default_factory=dict)
    scan_targets: list[Path] = field(default_factory=list)
    severity_overrides: dict[str, Severity] = field(default_factory=dict)
    # CP-5 — creds-expiry per-kind "expiring" 경고 임계 override (kind → 초).
    # 미지정 kind 는 코드 기본값(aws_sso 15min / 그 외 7d). anvyc.yaml
    # `doctor.creds_expiry.warn_thresholds` 에서 주입.
    creds_warn_thresholds: dict[str, float] = field(default_factory=dict)


class Check(Protocol):
    name: str

    def run(self, ctx: CheckContext) -> list[CheckResult]: ...
