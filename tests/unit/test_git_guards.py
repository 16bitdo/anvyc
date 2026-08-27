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


# --------------------------------------------------------------------------- #
# foreign hook 병합 — --force 가 남의 훅을 파괴하지 않는다
# --------------------------------------------------------------------------- #
# 계기 — 2026-08-27: security-scan 의 pre-push 에는 role-based-ruleset 의
# `claude-md-freshness` 블록이 들어 있었다. 옛 `--force` 는 훅을 통째 교체해 그것을
# 지웠다 — 백업 파일은 남지만 훅은 기능을 잃는다. #210 이 install-git-hooks.sh 에서
# 고친 것과 같은 결함이 여기에도 있었다.
#
# 삽입 위치는 취향이 아니라 **정확성**이다. pre-push 는 stdin 으로 ref 목록을 받고
# 가드는 `while read` 로 그것을 소비한다. 뒤에 붙이면 앞 본문이 stdin 을 이미 먹었을 때
# 가드가 조용히 무력화되므로, preamble 직후에 넣는다 (anvyc SoT 훅과 같은 배치).

_FOREIGN = """#!/usr/bin/env bash
set -eu

# >>> claude-md-freshness (managed by role-based-ruleset) >>>
echo freshness
# <<< claude-md-freshness <<<
echo mine
"""


def test_install_force_preserves_foreign_hook_body(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "r")
    hook = repo / ".git" / "hooks" / "pre-push"
    hook.write_text(_FOREIGN)

    res = install_pre_push_guard(repo, _POLICY, force=True)

    text = hook.read_text()
    assert res.status in {"installed", "merged"}
    assert GUARD_BEGIN in text
    assert "echo mine" in text  # 본문 보존
    assert "claude-md-freshness" in text  # 외부 managed-block 보존


def test_install_force_places_guard_before_hook_body(tmp_path: Path) -> None:
    """가드가 본문보다 앞에 와야 stdin(ref 목록)을 온전히 읽는다."""
    repo = _init_repo(tmp_path / "r")
    hook = repo / ".git" / "hooks" / "pre-push"
    hook.write_text(_FOREIGN)

    install_pre_push_guard(repo, _POLICY, force=True)

    text = hook.read_text()
    assert text.index(GUARD_BEGIN) < text.index("echo mine")


def test_install_force_keeps_shebang_first(tmp_path: Path) -> None:
    """shebang 앞에 삽입하면 스크립트가 아니게 된다."""
    repo = _init_repo(tmp_path / "r")
    hook = repo / ".git" / "hooks" / "pre-push"
    hook.write_text(_FOREIGN)

    install_pre_push_guard(repo, _POLICY, force=True)

    assert hook.read_text().startswith("#!/usr/bin/env bash\n")


def test_install_force_result_is_valid_bash(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "r")
    hook = repo / ".git" / "hooks" / "pre-push"
    hook.write_text(_FOREIGN)

    install_pre_push_guard(repo, _POLICY, force=True)

    subprocess.run(["bash", "-n", str(hook)], check=True)


def test_install_force_still_backs_up_original(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "r")
    hook = repo / ".git" / "hooks" / "pre-push"
    hook.write_text(_FOREIGN)

    install_pre_push_guard(repo, _POLICY, force=True)

    assert (repo / ".git" / "hooks" / "pre-push.pre-anvyc").read_text() == _FOREIGN


def test_install_refuses_hook_that_consumes_stdin(tmp_path: Path) -> None:
    """stdin 을 읽는 훅에는 넣지 않는다 — 어느 위치에 넣어도 한쪽이 굶는다.

    앞에 넣으면 본문이 ref 를 못 받고, 뒤에 넣으면 가드가 못 받아 **조용히** 통과시킨다.
    깨진 조합을 만드는 것보다 손대지 않고 사람에게 알리는 편이 낫다.
    """
    repo = _init_repo(tmp_path / "r")
    hook = repo / ".git" / "hooks" / "pre-push"
    body = "#!/usr/bin/env bash\nwhile read -r l s r x; do echo \"$l\"; done\n"
    hook.write_text(body)

    res = install_pre_push_guard(repo, _POLICY, force=True)

    assert res.status == "skipped-stdin-consumer"
    assert hook.read_text() == body  # 손대지 않는다
