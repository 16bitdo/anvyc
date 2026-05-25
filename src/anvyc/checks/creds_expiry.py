"""creds-expiry-within-7d check — CP-5 2/3.

`anvyc creds status` (CP-5 1/3) 의 detection 로직을 doctor 의 check 로
합류. CP-3 scheduler 가 이미 `anvyc doctor --strict --json` 일1회 호출 중
이므로, 본 check 만 등록되면 별도 wire 작업 없이 schduler health JSON 의
doctor payload 에 자동 노출됨 (자연 cross-axis 시너지).

Severity 매핑:
- credential.status = "expired"  → Severity.CRITICAL  (strict 모드 exit 1)
- credential.status = "expiring" → Severity.WARNING   (strict 모드 exit 1)
- credential.status = "valid" / "unknown" → result 없음 (silent)

Threshold: 본 check 이름에 명시된 7일. `--warn-days` 같은 동적 조정은
`anvyc creds status` CLI 에서 가능 (doctor check 자체는 7일 고정 —
이름에 박힌 contract).

doctor 의 read-only 원칙 준수: `probe_github_expiry=False` 로 호출해
gh CLI 의 외부 네트워크 접근 회피 (offline / CI 안전).
"""
from __future__ import annotations

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.core.creds import (
    STATUS_EXPIRED,
    STATUS_EXPIRING,
    collect_credentials,
)

CHECK_NAME = "creds-expiry-within-7d"
THRESHOLD_DAYS = 7


class CredsExpiryWithin7dCheck:
    name = CHECK_NAME

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        report = collect_credentials(
            warn_threshold_days=THRESHOLD_DAYS,
            probe_github_expiry=False,
        )
        out: list[CheckResult] = []
        for c in report.credentials:
            if c.status == STATUS_EXPIRED:
                out.append(
                    CheckResult(
                        check_name=self.name,
                        severity=Severity.CRITICAL,
                        message=(
                            f"{c.kind} '{c.identifier}' expired "
                            f"({c.expires_at or 'unknown'})"
                        ),
                        suggestion=(
                            "회전 권장: `anvyc creds rotate <kind>` (CP-5 3/3 PR 후 사용 가능). "
                            "현 시점은 source 별 수동 회전 — AWS SSO: `aws sso login`, "
                            "GitHub: `gh auth refresh` 또는 새 PAT 발급, Claude: re-login."
                        ),
                    )
                )
            elif c.status == STATUS_EXPIRING:
                out.append(
                    CheckResult(
                        check_name=self.name,
                        severity=Severity.WARNING,
                        message=(
                            f"{c.kind} '{c.identifier}' expires soon "
                            f"({c.expires_at}, ~{(c.expires_in_seconds or 0) // 86400}d 남음)"
                        ),
                        suggestion=(
                            "사전 회전 권장: `anvyc creds rotate <kind>` (CP-5 3/3 PR 후). "
                            "임계값 조정은 `anvyc creds status --warn-days N` 으로 직접 조회."
                        ),
                    )
                )
        return out
