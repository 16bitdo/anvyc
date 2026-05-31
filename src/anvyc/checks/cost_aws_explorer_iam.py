"""cost-aws-explorer-iam check — CP-13 PR-13C.

DESIGN §38.6 의 5종 cost check 중 하나. `~/.aws/config` 의 모든 profile 에
대해 `ce:GetCostAndUsage` 권한 보유 여부를 IAM
`SimulatePrincipalPolicy` 로 검증 (PR-13C 결정 Q2=a — simulate 는 호출 비용
0).

severity:
  * boto3 미설치 → WARNING (graceful skip, suggestion 으로 `pip install
    'anvyc[cost-aws]'` 안내)
  * profile 자체가 ~/.aws/config 에 없음 → result 없음 (silent)
  * SimulatePrincipalPolicy 결과 = "implicitDeny" / "explicitDeny" → WARNING
    + 정책 JSON 경로 안내
  * SSO 만료 / 인증 실패 → INFO (사용자가 직접 `aws sso login` 결정)
  * 권한 OK → result 없음 (silent — anvyc doctor 의 noise 최소화 원칙)

read-only — 본 check 자체가 외부 호출 (sts:GetCallerIdentity +
iam:SimulatePrincipalPolicy) 을 동반하지만 두 호출 모두 비용 0, 또
side-effect 0.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.utils.aws_config import load_aws_profile_names

CHECK_NAME = "cost-aws-explorer-iam"
TEMPLATE_RELATIVE_PATH = "templates/aws-cost-readonly.json"
REQUIRED_ACTION = "ce:GetCostAndUsage"


def _template_path() -> Path:
    """packaged IAM policy JSON 경로 (suggestion 안내용)."""
    return Path(__file__).parent.parent / TEMPLATE_RELATIVE_PATH


def _boto3_available() -> bool:
    return importlib.util.find_spec("boto3") is not None


class CostAwsExplorerIamCheck:
    """`ce:GetCostAndUsage` 권한 검증 (IAM simulate-principal-policy)."""

    name = CHECK_NAME

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        if not _boto3_available():
            return [
                CheckResult(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message=(
                        "AWS Cost Explorer adapter 비활성 — boto3 미설치 "
                        "(cost-aws optional dep)"
                    ),
                    suggestion=(
                        # --user 미사용: venv 안에서 `User site-packages are not
                        # visible in this virtualenv` 로 실패한다. pipx/uv/brew/venv
                        # 어디서든 복붙 가능하도록 plain install 로 안내.
                        "pip install 'anvyc[cost-aws]' "
                        "(설치 후 `anvyc cost collect --source aws` 가능)"
                    ),
                )
            ]

        profiles = sorted(load_aws_profile_names())
        if not profiles:
            return []  # ~/.aws/config 자체 없음 → silent

        results: list[CheckResult] = []
        for profile in profiles:
            results.extend(self._check_profile(profile))
        return results

    def _check_profile(self, profile: str) -> list[CheckResult]:
        """단일 profile 에 대해 sts caller id → iam simulate-principal-policy."""
        # 본 import 는 _boto3_available() 통과 후에만 실행.
        import boto3  # noqa: PLC0415
        from botocore.exceptions import BotoCoreError, ClientError  # noqa: PLC0415

        try:
            session = boto3.Session(profile_name=profile)
            sts = session.client("sts", region_name="us-east-1")
            caller = sts.get_caller_identity()
        except ClientError as e:
            return [self._sso_or_error_result(profile, e)]
        except BotoCoreError as e:
            return [self._sso_or_error_result(profile, e)]

        principal_arn = caller.get("Arn") or ""
        if not principal_arn:
            return []  # 비정상 응답 — silent

        try:
            iam = session.client("iam", region_name="us-east-1")
            sim = iam.simulate_principal_policy(
                PolicySourceArn=principal_arn,
                ActionNames=[REQUIRED_ACTION],
            )
        except ClientError as e:
            # iam:SimulatePrincipalPolicy 자체 권한 부재 등 — INFO 로 안내
            return [
                CheckResult(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message=(
                        f"profile {profile!r}: IAM simulate 권한 부재 — "
                        f"권한 검증 보류 (Cost Explorer 실호출 시 실 검증)"
                    ),
                    suggestion=str(e)[:200],
                )
            ]
        except BotoCoreError as e:
            return [self._sso_or_error_result(profile, e)]

        return self._classify_simulation(profile, sim, principal_arn)

    def _classify_simulation(
        self, profile: str, sim: dict[str, Any], principal_arn: str
    ) -> list[CheckResult]:
        """SimulatePrincipalPolicy 응답 → CheckResult."""
        eval_results = sim.get("EvaluationResults") or []
        for ev in eval_results:
            decision = ev.get("EvalDecision") or ""
            if decision == "allowed":
                return []  # silent OK
            if decision in {"implicitDeny", "explicitDeny"}:
                tmpl = _template_path()
                return [
                    CheckResult(
                        check_name=self.name,
                        severity=Severity.WARNING,
                        message=(
                            f"profile {profile!r} ({principal_arn}): "
                            f"{REQUIRED_ACTION} 권한 부재 ({decision})"
                        ),
                        suggestion=(
                            f"정책 attach: aws iam create-policy --policy-name "
                            f"AnvycCostReadonly --policy-document file://{tmpl} "
                            f"--profile {profile} (또는 console)"
                        ),
                    )
                ]
        return []

    def _sso_or_error_result(
        self, profile: str, exc: BaseException
    ) -> CheckResult:
        """SSO 만료 / 인증 실패 시 INFO 로 안내 (사용자 결정 영역)."""
        msg = str(exc).lower()
        if (
            "sso" in msg
            or "token has expired" in msg
            or "expiredtoken" in msg
            or "no credentials" in msg
        ):
            return CheckResult(
                check_name=self.name,
                severity=Severity.INFO,
                message=(
                    f"profile {profile!r}: SSO/credentials 만료 — 권한 검증 보류"
                ),
                suggestion=f"aws sso login --profile {profile}",
            )
        return CheckResult(
            check_name=self.name,
            severity=Severity.INFO,
            message=(
                f"profile {profile!r}: 인증 오류 — 권한 검증 보류"
            ),
            suggestion=str(exc)[:200],
        )
