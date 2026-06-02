# src/anvyc/checks/project_branch_protection.py
"""project-branch-protection check (spec L3).

등록 프로젝트 중 정책상 보호 대상(push_to_main_allowed=false)인 repo 에 대해
① 서버 ruleset 존재 ② 로컬 pre-push 가드 설치 를 검증, 불일치 시 WARNING.
접근 불가(whatap 등)·정책상 허용 repo·origin 없음 → silent(결과 0건).
"""
from __future__ import annotations

from pathlib import Path

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.core.branch_policy import resolve_policy
from anvyc.core.git_guards import GUARD_BEGIN, effective_hooks_dir
from anvyc.core.git_protect import _gh_api, get_ruleset
from anvyc.core.guard_targets import resolve_guard_targets
from anvyc.utils.git_remote import origin_owner_repo


def _has_repo_access(owner: str, repo: str) -> bool:
    rc, _, _ = _gh_api([f"repos/{owner}/{repo}", "--jq", ".full_name"])
    return rc == 0


def _hook_installed(repo_dir: Path) -> bool:
    hooks_dir, tracked = effective_hooks_dir(repo_dir)
    if tracked:
        return True  # tracked hooksPath 는 repo 자체 도구 책임 → 위반으로 보지 않음
    hook = hooks_dir / "pre-push"
    return hook.is_file() and GUARD_BEGIN in hook.read_text(errors="replace")


class ProjectBranchProtectionCheck:
    name = "project-branch-protection"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        results: list[CheckResult] = []
        for repo in resolve_guard_targets(None, None):
            policy = resolve_policy(repo)
            if policy.push_to_main_allowed:
                continue  # 보호 대상 아님
            owner_repo = origin_owner_repo(repo)
            if owner_repo is None:
                continue
            owner, name = owner_repo
            ruleset = get_ruleset(owner, name)
            if ruleset is None and not _has_repo_access(owner, name):
                continue  # 접근 불가 → silent (whatap 등)

            problems: list[str] = []
            if ruleset is None:
                problems.append("서버 ruleset(anvyc-pr-required) 미설정")
            if not _hook_installed(repo):
                problems.append("로컬 pre-push hook 미설치")

            if problems:
                results.append(
                    CheckResult(
                        check_name=self.name,
                        severity=Severity.WARNING,
                        message=f"{owner}/{name}: " + " / ".join(problems),
                        location=repo,
                        suggestion="anvyc guard protect --apply / anvyc guard install",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        check_name=self.name,
                        severity=Severity.INFO,
                        message=f"{owner}/{name}: ruleset + pre-push 가드 정합",
                        location=repo,
                    )
                )
        return results
