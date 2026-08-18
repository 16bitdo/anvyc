# src/anvyc/checks/project_branch_protection.py
"""project-branch-protection check (spec L3).

등록 프로젝트 중 정책상 보호 대상(push_to_main_allowed=false, 매니페스트 기반)인
repo 에 대해 ① 서버 ruleset 존재 ② 로컬 pre-push 가드 설치 를 검증, 불일치 시 WARNING.
정책 출처가 fallback(=role-based-ruleset 미발견)·정책상 main push 허용·origin 없음·
**enforce 불가(admin 아님 — private 404 또는 public read-only whatap 등)** → silent(결과 0건).

**archived repo** 는 쓰기가 403 이라 ruleset 설정이 영원히 불가능하므로 그 항목만 silent
(로컬 pre-push 훅은 archive 와 무관하게 설치 가능하므로 계속 검사한다).

네트워크: 보호 대상 repo 당 `gh api` 1~2회(get_ruleset, 필요 시 repo_admin)
+ ruleset 미설정으로 판정된 repo 만 repo_archived 1회 추가(정합 repo 에는 없음)
+ resolve_policy subprocess 1회 → repo 수에 비례. 무겁다면
`anvyc doctor --skip project-branch-protection`.
"""
from __future__ import annotations

from pathlib import Path

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.core.branch_policy import resolve_policy
from anvyc.core.git_guards import GUARD_BEGIN, effective_hooks_dir
from anvyc.core.git_protect import get_ruleset, gh_auth_state, repo_admin, repo_archived
from anvyc.core.guard_targets import resolve_guard_targets
from anvyc.utils.git_remote import origin_owner_repo


def _hook_problem(repo_dir: Path) -> tuple[str, str] | None:
    """git 이 실제 실행할 pre-push 훅에 가드 블록이 있는지 검사 — 없으면 사유.

    tracked hooksPath(worktree 내부)도 통과시키지 않는다. anvyc 는 그런 훅을
    clobber 하지 않고 skip 하는데, 이를 "repo 자체 도구 책임" 이라며 무조건 정합
    처리하면 **그 책임을 아무도 지지 않은 repo 가 초록으로 보고된다**
    (2026-08-18 anvyx: core.hooksPath=githooks 인데 githooks/pre-push 에 가드가
    없어 로컬 보호가 0인 채로 doctor 는 정합이었다).
    반환은 (사유, 해소책). tracked 에서는 `anvyc guard install` 이 skip 하므로 그 명령을
    해소책으로 안내하지 않는다 — 조치 불가능한 안내는 경고 무시를 훈련시킨다. 또한
    core.hooksPath 해제도 권하지 않는다: 그 설정이 해당 repo 의 **의도된 설계**일 수 있고
    (anvyx 는 그 경로로 로컬 CI 게이트를 돌린다) 해제하면 다른 보호가 무너진다.
    """
    hooks_dir, tracked = effective_hooks_dir(repo_dir)
    hook = hooks_dir / "pre-push"
    if hook.is_file() and GUARD_BEGIN in hook.read_text(errors="replace"):
        return None
    if tracked:
        return (
            f"로컬 pre-push 가드 없음 (tracked hooksPath={hooks_dir})",
            f"{hook} 에 anvyc-pr-guard 블록을 직접 추가 (anvyc 는 tracked 훅을 clobber 하지 않음)",
        )
    return ("로컬 pre-push hook 미설치", "anvyc guard install")


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
            fixes: list[str] = []
            # archived repo 는 GitHub 이 모든 쓰기를 403 으로 막아 ruleset 을 **영원히** 설정할
            # 수 없다. admin 권한은 그대로라 위 repo_admin 게이트로는 안 걸러진다 (2026-08-16
            # 실측: guard protect --apply → "Repository was archived so is read-only.
            # (HTTP 403)"). 조치 불가능한 경고를 매일 올리면서 실패하는 명령을 해소책으로
            # 안내하면 무시가 훈련되어 진짜 신호까지 함께 묻힌다.
            # `and` 단축평가로 repo_archived 는 **ruleset 미설정일 때만** 호출된다 — 정합
            # repo 까지 API 를 쓰면 헤더가 선언한 'repo 당 gh api 1~2회' 예산이 깨진다.
            if ruleset is None and not repo_archived(owner, name):
                problems.append("서버 ruleset(anvyc-pr-required) 미설정")
                fixes.append("anvyc guard protect --apply")
            # 로컬 훅은 archive 와 무관하게 설치 가능 — archived repo 에서도 계속 검사한다.
            hook_problem = _hook_problem(repo)
            if hook_problem:
                problems.append(hook_problem[0])
                fixes.append(hook_problem[1])

            if problems:
                results.append(
                    CheckResult(
                        check_name=self.name,
                        severity=Severity.WARNING,
                        message=f"{owner}/{name}: " + " / ".join(problems),
                        location=repo,
                        # 해소책은 실제로 걸린 문제의 것만 — 조치 불가능한 안내를 섞지 않는다.
                        suggestion=" / ".join(fixes),
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
