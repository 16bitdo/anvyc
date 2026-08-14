# src/anvyc/checks/project_branch_protection.py
"""project-branch-protection check (spec L3).

등록 프로젝트 중 정책상 보호 대상(push_to_main_allowed=false, 매니페스트 기반)인
repo 에 대해 ① 서버 ruleset 존재 ② 로컬 pre-push 가드 설치 를 검증, 불일치 시 WARNING.
정책 출처가 fallback(=role-based-ruleset 미발견)·정책상 main push 허용·origin 없음·
**enforce 불가(admin 아님 — private 404 또는 public read-only whatap 등)** → silent(결과 0건).

네트워크: 보호 대상 repo 당 `gh api` 1~2회(get_ruleset, 필요 시 repo_admin)
+ resolve_policy subprocess 1회 → repo 수에 비례. 무겁다면
`anvyc doctor --skip project-branch-protection`.
"""
from __future__ import annotations

from pathlib import Path

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.core.branch_policy import resolve_policy
from anvyc.core.git_guards import GUARD_BEGIN, effective_hooks_dir
from anvyc.core.git_protect import get_ruleset, gh_auth_state, repo_admin
from anvyc.core.guard_targets import resolve_guard_targets
from anvyc.utils.git_remote import origin_owner_repo


def _hook_installed(repo_dir: Path) -> bool:
    hooks_dir, tracked = effective_hooks_dir(repo_dir)
    if tracked:
        return True  # tracked hooksPath 는 repo 자체 도구 책임 → 위반으로 보지 않음
    hook = hooks_dir / "pre-push"
    return hook.is_file() and GUARD_BEGIN in hook.read_text(errors="replace")


class ProjectBranchProtectionCheck:
    name = "project-branch-protection"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        # preflight — 인증이 깨져 있으면 아래 per-repo 판정이 전부 "admin 아님" 으로
        # 보여 결과 0건이 된다. 그 0건은 "문제 없음" 이 아니라 "알 수 없음" 이므로,
        # 조용히 통과시키지 않고 한 건으로 알린다(2026-08-14 실사고).
        auth = gh_auth_state()
        if auth == "unauthenticated":
            return [
                CheckResult(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    message=(
                        "gh 인증 실패 — branch protection 을 판정할 수 없습니다. "
                        "결과 0건은 '문제 없음' 이 아니라 '알 수 없음' 입니다."
                    ),
                    # location 없음 — 특정 repo 가 아니라 gh 인증이라는 전역 조건이다.
                    suggestion="gh auth refresh -h github.com (또는 gh auth login)",
                )
            ]
        if auth != "ok":
            # gh 미설치·네트워크 불가 — 이 머신에선 검사가 성립하지 않는다. 여기서
            # 경고를 내면 gh 를 안 쓰는 머신마다 상시 빨강이 된다.
            return []

        results: list[CheckResult] = []
        aligned: list[str] = []
        for repo in resolve_guard_targets(None, None):
            policy = resolve_policy(repo)
            if policy.push_to_main_allowed:
                continue  # 보호 대상 아님
            if policy.source == "fallback":
                continue  # role-based-ruleset 미발견 → 판단 근거 없음 (이식성)
            owner_repo = origin_owner_repo(repo)
            if owner_repo is None:
                continue
            owner, name = owner_repo
            ruleset = get_ruleset(owner, name)
            if ruleset is None and not repo_admin(owner, name):
                continue  # enforce 불가(admin 아님 — private 404 또는 public read-only) → silent

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
                aligned.append(f"{owner}/{name}")

        if aligned:
            results.append(
                CheckResult(
                    check_name=self.name,
                    severity=Severity.INFO,
                    message=(
                        f"branch-protection 정합 repo {len(aligned)}개 "
                        f"— ruleset + pre-push 가드 일치"
                    ),
                )
            )
        return results
