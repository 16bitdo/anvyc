"""aws-profile-status check.

현재 shell 의 `AWS_PROFILE` 환경 변수와 `~/.aws/config` 의 profile 정의 정합성 점검.

- 미설정 → INFO (direnv .envrc 패턴 권장)
- 설정 + 정의됨 → INFO (현재 active profile 안내)
- 설정 + 정의 없음 → WARNING (오타/누락 안내)
"""
from __future__ import annotations

import os

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.utils.aws_config import load_aws_profile_names


class AwsProfileStatusCheck:
    name = "aws-profile-status"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        prof = os.environ.get("AWS_PROFILE")
        if not prof:
            return [
                CheckResult(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message="AWS_PROFILE 미설정 (현재 shell)",
                    suggestion=(
                        "프로젝트별 direnv .envrc 권장 — README §11 참조 "
                        "(예: 'export AWS_PROFILE=ws-dev' 를 .envrc 에 추가)"
                    ),
                )
            ]

        defined = load_aws_profile_names()
        if prof in defined:
            return [
                CheckResult(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message=f"AWS_PROFILE={prof} (정의됨)",
                )
            ]

        return [
            CheckResult(
                check_name=self.name,
                severity=Severity.WARNING,
                message=f"AWS_PROFILE={prof} 가 ~/.aws/config 에 정의 안 됨",
                suggestion=(
                    f"aws configure --profile {prof}  "
                    f"(또는 ~/.aws/config 에 [profile {prof}] section 추가)"
                ),
            )
        ]
