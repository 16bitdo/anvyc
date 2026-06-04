"""aws-account-status check — 현재 프로젝트(cwd scope)가 쓰는 AWS profile 의 인증/연결 상태.

`ctx.current_project_aws_profiles`(doctor 진입 cwd walk-up 으로 주입)에 한정.
scope=None/빈 frozenset → silent(cwd 가 프로젝트 아님/AWS profile 미사용).
read-only·offline — 네트워크 probe 는 `anvyc aws profile --probe` 에서만.
"""
from __future__ import annotations

from anvyc.checks.base import CheckContext, CheckResult
from anvyc.core.aws_profile_state import evaluate_profile_state, state_to_result


class AwsAccountStatusCheck:
    name = "aws-account-status"

    def run(self, ctx: CheckContext) -> list[CheckResult]:
        scope = ctx.current_project_aws_profiles
        if not scope:  # None 또는 빈 frozenset → silent
            return []
        out: list[CheckResult] = []
        for prof in sorted(scope):
            res = state_to_result(evaluate_profile_state(prof), check_name=self.name)
            if res is not None:
                out.append(res)
        return out
