"""hook-integrity-risk-gate check (CP-8 PR-B).

모든 `~/.claude*/settings.json` 에 risk-gate PreToolUse hook (CP-2) 이
배선되어 있는지 검증. ccinspector `module_verify` 의 read-only mirror —
anvyc 는 hook 본문/배선을 수정하지 않는다 (단방향 의존, DESIGN §7.7).

검증 기준 — settings.json 의 hooks.PreToolUse[*].hooks[*].command 의
문자열에 다음 hook 이름 3종이 모두 포함되었는지 확인:
  - destructive-keyword-block
  - aws-prod-account-confirm
  - account-routing-mismatch

일부 누락 → WARNING + 누락 목록 + ccinspector 활성화 권장 suggestion.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from anvyc.checks.base import CheckContext, CheckResult, Severity

RISK_GATE_HOOK_NAMES = (
    "destructive-keyword-block",
    "aws-prod-account-confirm",
    "account-routing-mismatch",
)


def discover_claude_settings(home: Path | None = None) -> list[Path]:
    """모든 `~/.claude*` 프로필의 settings.json 목록 (정렬)."""
    base = home or Path.home()
    targets: list[Path] = []
    for entry in sorted(base.glob(".claude*")):
        if not entry.is_dir():
            continue
        settings = entry / "settings.json"
        if settings.is_file():
            targets.append(settings)
    return targets


def wired_risk_gate_hooks(settings: dict[str, Any]) -> set[str]:
    """settings dict 에서 wire 된 risk-gate hook 이름 set."""
    found: set[str] = set()
    hooks_root = settings.get("hooks")
    if not isinstance(hooks_root, dict):
        return found
    pretool = hooks_root.get("PreToolUse")
    if not isinstance(pretool, list):
        return found
    for group in pretool:
        if not isinstance(group, dict):
            continue
        for h in group.get("hooks", []) or []:
            if not isinstance(h, dict):
                continue
            cmd = h.get("command")
            if not isinstance(cmd, str):
                continue
            for name in RISK_GATE_HOOK_NAMES:
                if name in cmd:
                    found.add(name)
    return found


class HookIntegrityRiskGateCheck:
    """CP-8 PR-B: risk-gate hook 배선 정합성 — 모든 Claude 프로필 검증."""

    name = "hook-integrity-risk-gate"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        results: list[CheckResult] = []
        settings_files = discover_claude_settings()
        if not settings_files:
            # Claude 프로필 자체 부재 — 본 check 비대상.
            return results
        for path in settings_files:
            try:
                raw = path.read_text(encoding="utf-8")
                data = json.loads(raw)
            except (OSError, json.JSONDecodeError):
                results.append(
                    CheckResult(
                        check_name=self.name,
                        severity=Severity.WARNING,
                        message="settings.json 파싱 실패",
                        location=path,
                        suggestion="JSON 무결성 확인 후 ccinspector verify 재실행",
                    )
                )
                continue
            wired = wired_risk_gate_hooks(data) if isinstance(data, dict) else set()
            missing = sorted(set(RISK_GATE_HOOK_NAMES) - wired)
            if missing:
                results.append(
                    CheckResult(
                        check_name=self.name,
                        severity=Severity.WARNING,
                        message=(
                            f"risk-gate hook 미배선 ({len(missing)}/"
                            f"{len(RISK_GATE_HOOK_NAMES)}): {missing}"
                        ),
                        location=path,
                        suggestion=(
                            "ccinspector risk-gate 모듈 활성화 후 "
                            "`bash scripts/install.sh` 재실행 (CP-2)"
                        ),
                    )
                )
        return results
