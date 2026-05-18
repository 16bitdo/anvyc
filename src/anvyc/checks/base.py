"""Doctor check 공통 타입.

DESIGN.md §27.2 참고.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol


class Severity(str, Enum):
    INFO = "info"
    INFO_ALIASED = "info-aliased"
    WARNING_FOREIGN = "warning-foreign"
    WARNING_DANGLING = "warning-dangling"
    CRITICAL = "critical"

    @property
    def is_blocking(self) -> bool:
        """strict 모드에서 exit 1 처리 대상."""
        return self in (Severity.WARNING_FOREIGN, Severity.WARNING_DANGLING, Severity.CRITICAL)


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


class Check(Protocol):
    name: str

    def run(self, ctx: CheckContext) -> list[CheckResult]: ...
