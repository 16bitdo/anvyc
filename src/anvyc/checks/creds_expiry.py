"""creds-expiry check — CP-5 2/3.

`anvyc creds status` (CP-5 1/3) 의 detection 로직을 doctor 의 check 로
합류. CP-3 scheduler 가 이미 `anvyc doctor --strict --json` 일1회 호출 중
이므로, 본 check 만 등록되면 별도 wire 작업 없이 scheduler health JSON 의
doctor payload 에 자동 노출됨 (자연 cross-axis 시너지).

Severity 매핑:
- credential.status = "expired"  → Severity.CRITICAL  (strict 모드 exit 1)
- credential.status = "expiring" → Severity.WARNING   (strict 모드 exit 1)
- credential.status = "valid" / "unknown" → result 없음 (silent)

Threshold (per-kind): long-lived 자격(github PAT / claude_oauth)은 7일 — 수동
회전 리드타임 필요. **aws_sso 는 15분(run-risk window)** — access token 이 짧게
만료(org 따라 ~1h)되고 refresh-on-demand(`aws sso login`)되므로 긴 임계는 영구
노이즈가 된다. 곧 시작할 run 도중 죽을 정도로 임박할 때만 경고(fresh 토큰은 valid,
마지막 15분에만 WARNING). expired(CRITICAL)는 임계 무관하게 그대로 잡음
(`creds.DEFAULT_KIND_WARN_DAYS`). 체크명에서 "within-7d" 를 제거 — 임계가 더
이상 단일 7일이 아님 (CP-14 게이트 정책 옵션화와 병행, 2026-05-30).

doctor 의 read-only 원칙 준수: `probe_github_expiry=False` 로 호출해
gh CLI 의 외부 네트워크 접근 회피 (offline / CI 안전).
"""
from __future__ import annotations

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.core.creds import (
    DEFAULT_KIND_WARN_DAYS,
    STATUS_EXPIRED,
    STATUS_EXPIRING,
    CredentialStatus,
    collect_credentials,
)

CHECK_NAME = "creds-expiry"
# long-lived 자격(github/claude_oauth) 기본 임계. aws_sso 는 per-kind override(15min).
THRESHOLD_DAYS = 7


def _cred_label(c: CredentialStatus) -> str:
    """식별 라벨 — aws_sso 는 sso_session 이름 우선 + profiles 요약(어느 계정/profile 인지).

    startUrl(불투명)만으로는 어느 profile 인지 모호 → sso_session 이름과 매핑된 profile
    을 노출. session 미해석(구형/매핑 실패) 시 startUrl 로 fallback.
    """
    if c.kind == "aws_sso" and c.sso_session:
        base = f"{c.kind} '{c.sso_session}'"
    else:
        base = f"{c.kind} '{c.identifier}'"
    if c.profiles:
        shown = ", ".join(c.profiles[:3])
        more = f" +{len(c.profiles) - 3}" if len(c.profiles) > 3 else ""
        return f"{base} (profiles: {shown}{more})"
    return base


def _rotate_hint(c: CredentialStatus) -> str:
    if c.kind == "aws_sso" and c.sso_session:
        return (
            f"회전: `aws sso login --sso-session {c.sso_session}` "
            "(또는 `aws sso login --profile <profile>`). "
            "`anvyc creds rotate <kind>` 는 CP-5 3/3 PR 후."
        )
    return (
        "회전 권장: `anvyc creds rotate <kind>` (CP-5 3/3 PR 후 사용 가능). "
        "현 시점은 source 별 수동 회전 — AWS SSO: `aws sso login`, "
        "GitHub: `gh auth refresh` 또는 새 PAT 발급, Claude: re-login."
    )


class CredsExpiryCheck:
    name = CHECK_NAME

    def run(self, ctx: CheckContext) -> list[CheckResult]:
        # anvyc.yaml `doctor.creds_expiry.warn_thresholds` (kind→초) override 를
        # 일 단위로 변환해 코드 기본값(DEFAULT_KIND_WARN_DAYS) 위에 merge.
        overrides = {
            kind: secs / 86400 for kind, secs in ctx.creds_warn_thresholds.items()
        }
        thresholds = {**DEFAULT_KIND_WARN_DAYS, **overrides}
        report = collect_credentials(
            warn_threshold_days=THRESHOLD_DAYS,
            kind_warn_days=thresholds,
            probe_github_expiry=False,
        )
        out: list[CheckResult] = []
        for c in report.credentials:
            if c.status == STATUS_EXPIRED:
                out.append(
                    CheckResult(
                        check_name=self.name,
                        severity=Severity.CRITICAL,
                        message=f"{_cred_label(c)} expired ({c.expires_at or 'unknown'})",
                        suggestion=_rotate_hint(c),
                    )
                )
            elif c.status == STATUS_EXPIRING:
                out.append(
                    CheckResult(
                        check_name=self.name,
                        severity=Severity.WARNING,
                        message=(
                            f"{_cred_label(c)} expires soon "
                            f"({c.expires_at}, ~{(c.expires_in_seconds or 0) // 86400}d 남음)"
                        ),
                        suggestion=(
                            "사전 회전 권장: `anvyc creds rotate <kind>` (CP-5 3/3 PR 후). "
                            "임계값 조정은 `anvyc creds status --warn-days N` 으로 직접 조회."
                        ),
                    )
                )
        return out
