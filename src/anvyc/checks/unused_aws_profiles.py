"""unused-aws-profiles check (v0.7.0).

`~/.aws/config` 에 정의됐지만 프로젝트 루트(`project_roots`) 아래 `.envrc`
의 `AWS_PROFILE` 값으로 사용되지 않는 profile 을 INFO 로 안내. cleanup 용 정보 (강제력 없음).

A1 (project-aws-profile-mapping) 의 reverse — A1 은 .envrc 에서 시작해 config
검증, 본 check 는 config 에서 시작해 .envrc 사용량 검증.
"""
from __future__ import annotations

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.utils.aws_config import load_aws_profile_names

_SAMPLE_N = 5


class UnusedAwsProfilesCheck:
    name = "unused-aws-profiles"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        defined = load_aws_profile_names()
        if not defined:
            return []
        # default profile 은 보통 fallback 으로 사용 — unused 판정에서 제외
        candidates = defined - {"default"}
        if not candidates:
            return []

        # 함수 내 import — resolve_project_roots 가 호출 시점에 config 를 로드하고
        # 테스트 monkeypatch(anvyc.core.project_roots)가 반영되도록 한다.
        from pathlib import Path

        from anvyc.checks.project_aws_profile import _iter_envrcs, _read_envrc_profile
        from anvyc.core.project_roots import resolve_project_roots

        used: set[str] = set()
        for root_str in resolve_project_roots():
            root = Path(root_str).expanduser()
            for envrc in _iter_envrcs(root):
                prof = _read_envrc_profile(envrc)
                if prof:
                    used.add(prof)

        unused = sorted(candidates - used)
        if not unused:
            return []

        sample = ", ".join(unused[:_SAMPLE_N])
        if len(unused) > _SAMPLE_N:
            sample += f", ... (+{len(unused) - _SAMPLE_N})"
        return [
            CheckResult(
                check_name=self.name,
                severity=Severity.INFO,
                message=(
                    f"{len(unused)} AWS profile(s) defined but not referenced in any "
                    f".envrc: {sample}"
                ),
                suggestion=(
                    "Each project that needs the profile should declare it in its "
                    "`.envrc` (export AWS_PROFILE=...), or remove the unused entry "
                    "from `~/.aws/config`."
                ),
            )
        ]
