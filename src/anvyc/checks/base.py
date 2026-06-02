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
    # creds-expiry project-scope (2026-05-31) — "실행 중인 프로젝트"가 쓰는 AWS profile 집합.
    #   None       → scoping 비활성(전역, 기존 동작 / 비-doctor 호출·테스트 기본)
    #   frozenset() → scoping 활성·매핑 profile 없음 → aws_sso 검사 silent
    #   frozenset({..}) → scoping 활성 → 교집합 있는 aws_sso 자격만 보고
    # doctor 진입(build_check_context)에서 cwd walk-up 으로 주입. github/claude_oauth
    # (profiles 빈 자격)은 scoping 무관 — 항상 보고.
    current_project_aws_profiles: frozenset[str] | None = None
    # owner→gh account(=ssh alias suffix) 매핑. 빈 dict = owner↔alias 라우팅 검증 skip
    # (무오탐 — 기존 동작 불변). anvyc.yaml `doctor.gh_owner_accounts` 에서 주입(rule 25 미러).
    gh_owner_accounts: dict[str, str] = field(default_factory=dict)


class Check(Protocol):
    name: str

    def run(self, ctx: CheckContext) -> list[CheckResult]: ...
