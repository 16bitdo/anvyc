"""sops-keys-available check.

DESIGN.md §31.7. sops/age binary 설치 + age identity file 존재 여부 확인.
모두 갖춰진 환경에서는 0 결과 (clean), 누락 시 WARNING + 설치 안내.

이 check 는 시스템 상태 점검이라 ctx.scan_targets 와 무관하게 동작.
"""
from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.core.extras import install_hint, is_available

DEFAULT_AGE_IDENTITY = Path("~/.config/sops/age/keys.txt").expanduser()


class SopsKeysCheck:
    name = "sops-keys-available"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        results: list[CheckResult] = []

        if not is_available("sops"):
            results.append(
                CheckResult(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message="sops binary 미설치 — secret_files 백업/적용 불가",
                    suggestion=install_hint("sops"),
                )
            )

        if not is_available("age"):
            results.append(
                CheckResult(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message="age binary 미설치 — SOPS age backend 사용 불가",
                    suggestion=install_hint("age"),
                )
            )

        identity = Path(
            os.environ.get("SOPS_AGE_KEY_FILE") or ctx.sops_identity_file or DEFAULT_AGE_IDENTITY
        ).expanduser()
        command = ctx.sops_key_cmd or os.environ.get("SOPS_AGE_KEY_CMD")
        command_available = False
        if command:
            try:
                args = shlex.split(command)
                command_available = bool(args and shutil.which(args[0]))
            except ValueError:
                pass
            if not command_available:
                results.append(CheckResult(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message="SOPS age key command 실행 파일 부재 또는 잘못된 명령 형식",
                    suggestion="security.sops.age_key_cmd 또는 SOPS_AGE_KEY_CMD 설정 확인",
                ))

        # Provider discovery only: do not execute commands or prompt for secrets in doctor.
        # A successful decrypt is required to verify authorization and key correspondence.
        if not (identity.is_file() or os.environ.get("SOPS_AGE_KEY") or command_available):
            results.append(
                CheckResult(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message=f"age identity file 부재: {identity}",
                    suggestion=(
                        "mkdir -p ~/.config/sops/age && "
                        "age-keygen -o ~/.config/sops/age/keys.txt  "
                        "(public key 는 anvyc.yaml security.sops.age_recipients 에 등록). "
                        "또는 security.sops.age_key_cmd 로 1Password 키 조회 명령 설정"
                    ),
                )
            )

        return results
