# tests/unit/test_git_guards.py
"""Unit tests for anvyc.core.git_guards."""
from __future__ import annotations

import subprocess
from pathlib import Path

from anvyc.core.branch_policy import BranchPolicy
from anvyc.core.git_guards import (
    GUARD_BEGIN,
    GUARD_END,
    install_pre_push_guard,
    render_guard_block,
)

_POLICY = BranchPolicy(
    default_branch="main", protected_branches=("main",),
    push_to_main_allowed=False, pr_required=True, pr_reviewers_min=0,
    merge_strategy="squash", source="manifest",
)


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    return path


def test_render_block_has_markers_and_guard() -> None:
    block = render_guard_block(_POLICY)
    assert GUARD_BEGIN in block and GUARD_END in block
    assert '__anvyc_allowed="false"' in block
    assert "refs/heads/$_b" in block


def test_install_fresh_creates_executable_hook(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "r")
    res = install_pre_push_guard(repo, _POLICY)
    hook = repo / ".git" / "hooks" / "pre-push"
    assert res.status == "installed"
    assert hook.is_file()
    assert hook.stat().st_mode & 0o111  # executable
    assert GUARD_BEGIN in hook.read_text()


def test_install_idempotent_updates_block(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "r")
    install_pre_push_guard(repo, _POLICY)
    res2 = install_pre_push_guard(repo, _POLICY)
    hook = repo / ".git" / "hooks" / "pre-push"
    assert res2.status == "updated"
    assert hook.read_text().count(GUARD_BEGIN) == 1  # 중복 없음


def test_install_skips_foreign_hook(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "r")
    hook = repo / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/bin/sh\necho mine\n")
    res = install_pre_push_guard(repo, _POLICY)
    assert res.status == "skipped-foreign"
    assert "echo mine" in hook.read_text()  # 보존


def test_install_force_backs_up_foreign(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "r")
    hook = repo / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/bin/sh\necho mine\n")
    res = install_pre_push_guard(repo, _POLICY, force=True)
    assert res.status == "installed"
    assert (repo / ".git" / "hooks" / "pre-push.pre-anvyc").read_text() == "#!/bin/sh\necho mine\n"
    assert GUARD_BEGIN in hook.read_text()


def test_install_skips_tracked_hookspath(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "r")
    (repo / "scripts" / "hooks").mkdir(parents=True)
    subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath", "scripts/hooks"], check=True)
    res = install_pre_push_guard(repo, _POLICY)
    assert res.status == "skipped-tracked-hooks"


def test_install_allowed_policy_still_installs_noop_guard(tmp_path: Path) -> None:
    """push_to_main_allowed=True 정책도 설치는 됨(런타임 no-op). 블록에 allowed=true."""
    from anvyc.core.branch_policy import BranchPolicy
    allowed = BranchPolicy(
        default_branch="main", protected_branches=("main",), push_to_main_allowed=True,
        pr_required=False, pr_reviewers_min=0, merge_strategy="squash", source="manifest",
    )
    repo = _init_repo(tmp_path / "r")
    res = install_pre_push_guard(repo, allowed)
    assert res.status == "installed"
    hook = repo / ".git" / "hooks" / "pre-push"
    assert '__anvyc_allowed="true"' in hook.read_text()


def test_install_in_linked_worktree_uses_common_hooks(tmp_path: Path) -> None:
    """linked worktree(.git 이 파일)에서 크래시 없이 공용 hooks 에 설치된다."""
    main = _init_repo(tmp_path / "main")
    subprocess.run(
        ["git", "-C", str(main), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "--allow-empty", "-q", "-m", "init"], check=True,
    )
    wt = tmp_path / "wt"
    subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", "-b", "feat", str(wt)], check=True)
    assert (wt / ".git").is_file()  # linked worktree marker
    res = install_pre_push_guard(wt, _POLICY)
    assert res.status == "installed"
    # 공용 hooks dir(main/.git/hooks)에 설치
    assert (main / ".git" / "hooks" / "pre-push").is_file()
