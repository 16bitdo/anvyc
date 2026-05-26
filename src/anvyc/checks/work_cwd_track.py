"""work-cwd-track-wired check (CP-12 PR-12F).

모든 `~/.claude*/settings.json` 에 work-cwd-track hook (Phase A CwdChanged +
Phase B PostToolUse) 가 배선되어 있는지 + `env.WORK_CWD_CACHE` 가 주입되어
있는지 검증.

ccinspector `module_verify` (work-cwd-track, cci#16/#18) 의 read-only mirror
— anvyc 는 hook 본문/배선을 수정하지 않는다 (단방향 의존, DESIGN §7.7).
별 채널로 cross-validation 만 수행.

검증 기준:
- hooks.CwdChanged[*].hooks[*].command 에 'work-cwd-track' 포함 (Phase A, 필수)
- hooks.PostToolUse[*].hooks[*].command 에 'work-cwd-track' 포함 (Phase B, 권장)
- env.WORK_CWD_CACHE 가 set 됨 (필수)

누락 시 WARNING + 누락 항목 명시 + ccinspector 활성화 권장 suggestion.
"""
from __future__ import annotations

import json
from typing import Any

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.checks.hook_integrity import discover_claude_settings

WORK_CWD_TRACK_HOOK_NAME = "work-cwd-track"
ENV_KEY = "WORK_CWD_CACHE"


def _has_work_cwd_track_in_event(settings: dict[str, Any], event_name: str) -> bool:
    """Return True if hooks.<event_name> contains any command matching 'work-cwd-track'."""
    hooks_root = settings.get("hooks")
    if not isinstance(hooks_root, dict):
        return False
    event_list = hooks_root.get(event_name)
    if not isinstance(event_list, list):
        return False
    for group in event_list:
        if not isinstance(group, dict):
            continue
        for h in group.get("hooks", []) or []:
            if not isinstance(h, dict):
                continue
            cmd = h.get("command")
            if isinstance(cmd, str) and WORK_CWD_TRACK_HOOK_NAME in cmd:
                return True
    return False


def _has_env_cache(settings: dict[str, Any]) -> bool:
    env = settings.get("env")
    if not isinstance(env, dict):
        return False
    val = env.get(ENV_KEY)
    return isinstance(val, str) and bool(val.strip())


class WorkCwdTrackWiredCheck:
    """CP-12 PR-12F: work-cwd-track hook + env 배선 정합성."""

    name = "work-cwd-track-wired"

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
                        suggestion="JSON 무결성 확인 후 ccinspector install.sh 재실행",
                    )
                )
                continue
            if not isinstance(data, dict):
                continue

            phase_a_wired = _has_work_cwd_track_in_event(data, "CwdChanged")
            phase_b_wired = _has_work_cwd_track_in_event(data, "PostToolUse")
            env_wired = _has_env_cache(data)

            missing: list[str] = []
            if not phase_a_wired:
                missing.append("Phase A (CwdChanged)")
            if not phase_b_wired:
                missing.append("Phase B (PostToolUse Read|Write|Edit|MultiEdit)")
            if not env_wired:
                missing.append(f"env.{ENV_KEY}")

            if missing:
                results.append(
                    CheckResult(
                        check_name=self.name,
                        severity=Severity.WARNING,
                        message=(
                            f"work-cwd-track 미배선 ({len(missing)} 항목): "
                            f"{', '.join(missing)}"
                        ),
                        location=path,
                        suggestion=(
                            "ccinspector module_work_cwd_track=1 활성화 후 "
                            "`bash scripts/install.sh` 재실행 (CP-12 PR-12B/D')"
                        ),
                    )
                )
        return results
