"""sops-keys-available check.

DESIGN.md §31.7. sops/age binary 설치 + age identity file 존재 여부 확인.
모두 갖춰진 환경에서는 0 결과 (clean), 누락 시 WARNING + 설치 안내.

이 check 는 시스템 상태 점검이라 ctx.scan_targets 와 무관하게 동작.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from anvyc.checks.base import CheckContext, CheckResult, Severity

DEFAULT_AGE_IDENTITY = Path("~/.config/sops/age/keys.txt").expanduser()


class SopsKeysCheck:
    name = "sops-keys-available"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        results: list[CheckResult] = []

        if not shutil.which("sops"):
            results.append(
                CheckResult(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message="sops binary 미설치 — secret_files 백업/적용 불가",
                    suggestion="brew install sops  (또는 https://github.com/getsops/sops)",
                )
            )

        if not shutil.which("age"):
            results.append(
                CheckResult(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message="age binary 미설치 — SOPS age backend 사용 불가",
                    suggestion="brew install age",
                )
            )

        if not DEFAULT_AGE_IDENTITY.exists():
            results.append(
                CheckResult(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message=f"age identity file 부재: {DEFAULT_AGE_IDENTITY}",
                    suggestion=(
                        "mkdir -p ~/.config/sops/age && "
                        "age-keygen -o ~/.config/sops/age/keys.txt  "
                        "(public key 는 anvyc.yaml security.sops.age_recipients 에 등록)"
                    ),
                )
            )

        return results
