"""secret-registry-valid check — CP-15 Phase 1.

`anvyc.yaml` 의 `secrets:` 레지스트리 entry 가 구조적으로 유효한지 검증한다.
doctor 의 read-only / offline 원칙 준수 — `probe=False` 로 호출해 backend CLI
외부 접근 없이 핸들 필드 누락 + 미지 backend 만 본다 (resolvability probe 는
`anvyc secret list` 에서 수행).

Severity:
- status="invalid" (backend 별 필수 핸들 필드 누락)   → WARNING (strict exit 1)
- status="unknown" (미지 backend)                      → INFO
- status="ok"                                          → result 없음 (silent)
"""
from __future__ import annotations

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.core.secrets import STATUS_INVALID, STATUS_UNKNOWN, collect_secrets

CHECK_NAME = "secret-registry-valid"


class SecretRegistryValidCheck:
    name = CHECK_NAME

    def __init__(self, *, config_path: object | None = None) -> None:
        # 테스트 주입용 — 기본은 None (default candidate path 로드)
        self._config_path = config_path

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        report = collect_secrets(config_path=self._config_path, probe=False)  # type: ignore[arg-type]
        out: list[CheckResult] = []
        for e in report.entries:
            if e.status == STATUS_INVALID:
                out.append(
                    CheckResult(
                        check_name=self.name,
                        severity=Severity.WARNING,
                        message=f"secret '{e.name}' ({e.backend}) 핸들 무효: {e.detail}",
                        suggestion="anvyc.yaml 의 secrets.entries 항목에 backend 별 필수 필드를 채우세요.",
                    )
                )
            elif e.status == STATUS_UNKNOWN:
                out.append(
                    CheckResult(
                        check_name=self.name,
                        severity=Severity.INFO,
                        message=f"secret '{e.name}' backend '{e.backend}' 미지원 — {e.detail}",
                        suggestion="지원 backend: op / sops / keychain / aws-vault.",
                    )
                )
        return out
