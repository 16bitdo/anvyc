"""ruleset-deploy-drift check (L2 관측, read-only).

role-based-ruleset(L1 SoT) 로컬 clone 이 origin/main 보다 뒤처져 있으면 배포된
가드/룰(hook · .cursor/rules · CLAUDE.md)이 stale 일 수 있음을 read-only 로 관측한다.
anvyc 는 SoT 를 수정하지 않는다 (단방향 의존, DESIGN §7.7) — pull/redeploy 는
사용자 / L3(ccinspector) 몫. 본 check 는 "뒤처짐" 만 보고한다.

판정: `git -C <repo> rev-list --count HEAD..origin/main` > 0 → WARNING (N 커밋 뒤).
offline-safe — network fetch 안 함(마지막 fetch 된 origin/main 기준). 비-git / ref 부재 /
오류 → silent skip (무오탐).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from anvyc.checks.base import CheckContext, CheckResult, Severity


def ruleset_repo() -> Path:
    """role-based-ruleset 로컬 clone 경로 (관례: ~/dev/role-based-ruleset)."""
    return Path.home() / "dev" / "role-based-ruleset"


def behind_count(repo: Path) -> int | None:
    """HEAD 가 origin/main 보다 몇 커밋 뒤인지. 비-git / ref 부재 / 오류 → None."""
    if not (repo / ".git").is_dir():
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "rev-list", "--count", "HEAD..origin/main"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return None


class RulesetDeployDriftCheck:
    """L2(read-only): role-based-ruleset clone 이 origin/main 보다 뒤처졌는지 관측."""

    name = "ruleset-deploy-drift"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        repo = ruleset_repo()
        n = behind_count(repo)
        if not n:  # None(비대상) 또는 0(최신) → 보고 없음
            return []
        return [
            CheckResult(
                check_name=self.name,
                severity=Severity.WARNING,
                message=(
                    f"role-based-ruleset clone 이 origin/main 보다 {n} 커밋 뒤 — "
                    "배포된 가드/룰(hook · .cursor/rules · CLAUDE.md) stale 가능"
                ),
                location=repo,
                suggestion=(
                    "git -C ~/dev/role-based-ruleset pull --ff-only 후 "
                    "ccinspector wire-hooks / generate_claude_md.py --apply 재실행 (L3 배포)"
                ),
            )
        ]
