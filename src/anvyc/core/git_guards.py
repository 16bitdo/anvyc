# src/anvyc/core/git_guards.py
"""로컬 pre-push 가드 — 보호 브랜치 직접 push 를 차단한다.

`anvyc guard install` 이 대상 repo 의 effective hooks dir 에 marker 블록을 설치한다.
정책 스냅샷(protected/allowed)을 hook 에 임베드 → push 시점에 ruleset repo 의존 없음.
core.hooksPath 가 worktree 내부(tracked)면 clobber 금지하고 skip 한다.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from anvyc.core.branch_policy import BranchPolicy

GuardStatus = Literal["installed", "updated", "skipped-foreign", "skipped-tracked-hooks"]

GUARD_BEGIN = "# >>> anvyc-pr-guard >>>"
GUARD_END = "# <<< anvyc-pr-guard <<<"
_SHEBANG = "#!/usr/bin/env bash\nset -euo pipefail\n"


def render_guard_block(policy: BranchPolicy) -> str:
    protected = " ".join(policy.protected_branches)
    allowed = "true" if policy.push_to_main_allowed else "false"
    return (
        f"{GUARD_BEGIN}\n"
        f"# auto-generated; managed by `anvyc guard install`. policy_source={policy.source}\n"
        f'__anvyc_protected="{protected}"\n'
        f'__anvyc_allowed="{allowed}"\n'
        'if [ "$__anvyc_allowed" != "true" ]; then\n'
        "  while read -r _lref _lsha _rref _rsha; do\n"
        "    for _b in $__anvyc_protected; do\n"
        '      if [ "$_rref" = "refs/heads/$_b" ]; then\n'
        '        echo "" >&2\n'
        "        echo \"anvyc guard: '$_b' 직접 push 차단 (push_to_main_allowed=false).\" >&2\n"
        '        echo "  작업 브랜치 + PR 로 진행하세요:" >&2\n'
        '        echo "    git switch -c feat/<topic> && git push -u origin feat/<topic> && gh pr create --fill" >&2\n'
        "        exit 1\n"
        "      fi\n"
        "    done\n"
        "  done\n"
        "fi\n"
        f"{GUARD_END}\n"
    )


def effective_hooks_dir(repo_dir: Path) -> tuple[Path, bool]:
    """(hooks_dir, tracked_in_worktree) 반환.

    core.hooksPath 가 설정돼 있으면 그 경로를, 아니면 git common dir(`--git-common-dir`,
    linked worktree 도 안전)의 hooks 를 쓴다. tracked = worktree 내부이면서 .git 영역 밖
    (예: core.hooksPath=scripts/hooks) → anvyc 가 clobber 하지 않고 skip 하기 위함.
    """
    try:
        cfg = subprocess.run(
            ["git", "-C", str(repo_dir), "config", "--get", "core.hooksPath"],
            capture_output=True, text=True, check=False, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return repo_dir / ".git" / "hooks", False
    hp = cfg.stdout.strip() if cfg.returncode == 0 else ""
    if hp:
        hooks = Path(hp) if Path(hp).is_absolute() else (repo_dir / hp)
        try:
            rel = hooks.resolve().relative_to(repo_dir.resolve())
            tracked = rel.parts[:1] != (".git",)
        except (ValueError, OSError):
            tracked = False
        return hooks, tracked
    # custom hooksPath 없음 → common git dir 의 hooks (worktree 안전)
    try:
        cd = subprocess.run(
            ["git", "-C", str(repo_dir), "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, check=False, timeout=5,
        )
        common = cd.stdout.strip() if cd.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        common = ""
    if not common:
        return repo_dir / ".git" / "hooks", False
    common_path = Path(common) if Path(common).is_absolute() else (repo_dir / common)
    return common_path / "hooks", False


@dataclass
class GuardInstallResult:
    repo: Path
    status: GuardStatus
    detail: str = ""


def install_pre_push_guard(
    repo_dir: Path, policy: BranchPolicy, *, force: bool = False
) -> GuardInstallResult:
    hooks_dir, tracked = effective_hooks_dir(repo_dir)
    if tracked:
        return GuardInstallResult(repo_dir, "skipped-tracked-hooks", str(hooks_dir))
    hook = hooks_dir / "pre-push"
    block = render_guard_block(policy)
    if not hook.exists():
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook.write_text(_SHEBANG + block)
        hook.chmod(0o755)
        return GuardInstallResult(repo_dir, "installed")
    text = hook.read_text()
    if GUARD_BEGIN in text:
        pre = text.split(GUARD_BEGIN)[0]
        post = text.split(GUARD_END, 1)[1] if GUARD_END in text else "\n"
        hook.write_text(pre + block + post)
        hook.chmod(0o755)
        return GuardInstallResult(repo_dir, "updated")
    if not force:
        return GuardInstallResult(repo_dir, "skipped-foreign", str(hook))
    (hooks_dir / "pre-push.pre-anvyc").write_text(text)
    hook.write_text(_SHEBANG + block)
    hook.chmod(0o755)
    return GuardInstallResult(repo_dir, "installed", "backup=pre-push.pre-anvyc")
