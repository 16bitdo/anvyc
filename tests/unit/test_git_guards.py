# tests/unit/test_git_guards.py
"""Unit tests for anvyc.core.git_guards."""
from __future__ import annotations

import re
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


# --------------------------------------------------------------------------- #
# skip status 는 막다른 길이 아니라 다음 행동을 알려준다
# --------------------------------------------------------------------------- #
# 계기 — 2026-08-30: `skipped-stdin-consumer` 의 detail 이 훅 경로뿐이라, 받은 사람은
# "왜 안 되는지"도 "무엇을 하면 되는지"도 알 수 없었다. 정답 패턴은 이미 실재한다 —
# anvyx githooks/pre-push 가 stdin 을 한 번 읽어 `$REFS` 에 담고 각 소비자에 서브셸로
# 먹여, 가드 블록을 byte-identical 로 유지한 채 공존시킨다.


def test_stdin_consumer_skip_explains_remedy(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "r")
    hook = repo / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/usr/bin/env bash\nwhile read -r a b c d; do :; done\n")

    res = install_pre_push_guard(repo, _POLICY, force=True)

    assert res.status == "skipped-stdin-consumer"
    assert str(hook) in res.detail  # 어느 파일인지
    assert "REFS" in res.detail  # 무엇을 하면 되는지
    assert "anvyx" in res.detail  # 동작하는 참조 구현


def test_foreign_skip_mentions_force_is_non_destructive(tmp_path: Path) -> None:
    """`--force` 는 #211 이후 '덮어쓴다' 가 아니라 '병합한다' — 낡은 인식을 바로잡는다."""
    repo = _init_repo(tmp_path / "r")
    hook = repo / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/bin/sh\necho mine\n")

    res = install_pre_push_guard(repo, _POLICY)

    assert res.status == "skipped-foreign"
    assert str(hook) in res.detail
    assert "--force" in res.detail


def test_remedy_survives_console_rendering(tmp_path: Path) -> None:
    """안내가 rich 마크업 파서에 먹히지 않고 터미널까지 온전히 도착해야 한다.

    `[ -t 0 ]` 은 rich 가 태그로 해석할 수 있는 형태다 — 문자열이 맞는 것과 사용자에게
    제대로 보이는 것은 다른 명제이고, 후자가 구속되지 않으면 안내는 조용히 훼손된다.
    """
    import os
    import sys

    repo = _init_repo(tmp_path / "r")
    (repo / ".git" / "hooks" / "pre-push").write_text(
        "#!/usr/bin/env bash\nwhile read -r a b c d; do :; done\n"
    )
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")}
    env.pop("FORCE_COLOR", None)
    r = subprocess.run(
        [sys.executable, "-m", "anvyc", "guard", "install", "--force", "--project", str(repo)],
        capture_output=True, text=True, env=env,
    )

    assert r.returncode == 0, r.stderr
    out = " ".join(r.stdout.split())  # 터미널 폭에 따른 줄바꿈 흡수
    assert "[ -t 0 ]" in out, f"rich 가 대괄호를 삼켰다: {r.stdout!r}"
    assert "REFS" in out
    assert "anvyx" in out
    assert "**" not in out  # 렌더 안 되는 markdown 강조가 그대로 노출되면 안 된다


# --- 머지된 브랜치 부활 차단 -------------------------------------------------
#
# PR 머지 후 GitHub 이 원격 브랜치를 지워도 로컬은 그 브랜치에 남아 있다. 거기서
# 커밋하고 push 하면 브랜치가 되살아나고, 그 커밋은 refs/pull 보호를 못 받는다.
# 가드는 「원격 sha 가 0 + upstream 이 설정돼 있음」으로 그 순간만 집어낸다 —
# 신규 브랜치의 첫 push -u 는 그 시점에 upstream 이 아직 없어 구분된다.


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=check
    )


def _repo_with_remote(
    tmp_path: Path,
    policy: BranchPolicy = _POLICY,
    *,
    seed_main: bool = False,
    extra_remotes: tuple[str, ...] = (),
) -> Path:
    """가드가 설치되고 bare 원격이 붙은, 커밋 1개짜리 저장소.

    seed_main — origin 에 main 을 올리고 fetch 해 `origin/main` 추적 ref 를 만든다.
    가드가 main 직접 push 를 막으므로 **설치 전에** 올린다.
    """
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    repo = _init_repo(tmp_path / "r")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("hi\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-qm", "init")
    _git(repo, "remote", "add", "origin", str(remote))
    for name in extra_remotes:
        extra = tmp_path / f"{name}.git"
        subprocess.run(["git", "init", "--bare", "-q", str(extra)], check=True)
        _git(repo, "remote", "add", name, str(extra))
    if seed_main:
        _git(repo, "push", "-q", "origin", "main")
        _git(repo, "fetch", "-q", "origin")
    install_pre_push_guard(repo, policy)
    return repo


def _commit(repo: Path, text: str, msg: str) -> None:
    (repo / "a.txt").write_text(text)
    _git(repo, "commit", "-qam", msg)


def test_render_block_has_revived_branch_guard() -> None:
    block = render_guard_block(_POLICY)
    assert "__anvyc_zero=" in block
    assert "symbolic-ref" in block  # `push origin HEAD` 의 local ref 를 실제 브랜치로 푼다


def test_revived_guard_allows_first_push_of_new_branch(tmp_path: Path) -> None:
    repo = _repo_with_remote(tmp_path)
    _git(repo, "switch", "-qc", "feat/x")
    _commit(repo, "x\n", "c1")

    r = _git(repo, "push", "-u", "origin", "feat/x", check=False)

    assert r.returncode == 0, r.stderr


def test_revived_guard_blocks_push_to_deleted_branch(tmp_path: Path) -> None:
    repo = _repo_with_remote(tmp_path)
    _git(repo, "switch", "-qc", "feat/x")
    _commit(repo, "x\n", "c1")
    _git(repo, "push", "-u", "origin", "feat/x")
    _git(repo, "push", "origin", "--delete", "feat/x")  # 머지 후 자동 삭제 재현
    _commit(repo, "y\n", "c2")

    r = _git(repo, "push", "origin", "feat/x", check=False)

    assert r.returncode != 0
    assert "원격에서 사라진 브랜치" in r.stderr


def test_revived_guard_runs_when_push_to_main_allowed(tmp_path: Path) -> None:
    """부활 차단은 push_to_main_allowed 와 무관하게 동작해야 한다."""
    allowed = BranchPolicy(
        default_branch="main", protected_branches=("main",), push_to_main_allowed=True,
        pr_required=False, pr_reviewers_min=0, merge_strategy="merge", source="manifest",
    )
    repo = _repo_with_remote(tmp_path, allowed)
    _git(repo, "switch", "-qc", "feat/x")
    _commit(repo, "x\n", "c1")
    _git(repo, "push", "-u", "origin", "feat/x")
    _git(repo, "push", "origin", "--delete", "feat/x")
    _commit(repo, "y\n", "c2")

    r = _git(repo, "push", "origin", "feat/x", check=False)

    assert r.returncode != 0
    assert "원격에서 사라진 브랜치" in r.stderr


# --- #219 오탐·미탐 회귀 ------------------------------------------------------
#
# #219 는 「upstream 이 있으면 부활」로 봤다. git 기본값 branch.autoSetupMerge=true 는
# 원격 추적 브랜치에서 딴 순간 upstream 을 박으므로(`switch -c X origin/main`,
# `worktree add -b X <p> origin/main`) 그런 브랜치의 첫 push 가 차단됐다.
# 부활은 「push 하는 로컬 브랜치의 upstream 이 push 대상과 같고, 같은 원격일 때」다.


def test_revived_guard_allows_branch_from_remote_tracking(tmp_path: Path) -> None:
    repo = _repo_with_remote(tmp_path, seed_main=True)
    _git(repo, "switch", "-qc", "feat/x", "origin/main")
    # 전제 — autoSetupMerge 가 upstream 을 main 으로 박았다
    assert _git(repo, "config", "branch.feat/x.merge").stdout.strip() == "refs/heads/main"
    _commit(repo, "x\n", "c1")

    r = _git(repo, "push", "-u", "origin", "feat/x", check=False)

    assert r.returncode == 0, r.stderr


def test_revived_guard_allows_worktree_branch_from_remote_tracking(tmp_path: Path) -> None:
    """worktree 를 원격 추적 ref 에서 만들 때도 같다 — 실제 저장소들에서 확인된 생성 명령이다."""
    repo = _repo_with_remote(tmp_path, seed_main=True)
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "feat/x", str(wt), "origin/main")
    _commit(wt, "x\n", "c1")

    r = _git(wt, "push", "-u", "origin", "HEAD", check=False)

    assert r.returncode == 0, r.stderr


def test_revived_guard_allows_first_push_after_branch_rename(tmp_path: Path) -> None:
    """push 후 `git branch -m old new` 하면 upstream(refs/heads/old)이 새 이름에 따라온다.
    new 의 첫 push 는 부활이 아니다."""
    repo = _repo_with_remote(tmp_path)
    _git(repo, "switch", "-qc", "feat/old")
    _commit(repo, "x\n", "c1")
    _git(repo, "push", "-u", "origin", "feat/old")
    _git(repo, "branch", "-m", "feat/old", "feat/new")
    # 전제 — upstream 이 옛 이름을 그대로 가리킨다
    assert _git(repo, "config", "branch.feat/new.merge").stdout.strip() == "refs/heads/feat/old"
    _commit(repo, "y\n", "c2")

    r = _git(repo, "push", "-u", "origin", "feat/new", check=False)

    assert r.returncode == 0, r.stderr


def test_revived_guard_blocks_revival_via_push_head(tmp_path: Path) -> None:
    """`git push origin HEAD` 는 훅 stdin 의 local ref 가 `HEAD` 그대로 온다.
    local ref 로만 브랜치를 찾으면 이 흔한 부활을 놓친다."""
    repo = _repo_with_remote(tmp_path)
    _git(repo, "switch", "-qc", "feat/x")
    _commit(repo, "x\n", "c1")
    _git(repo, "push", "-u", "origin", "feat/x")
    _git(repo, "push", "origin", "--delete", "feat/x")
    _commit(repo, "y\n", "c2")

    r = _git(repo, "push", "origin", "HEAD", check=False)

    assert r.returncode != 0
    assert "원격에서 사라진 브랜치" in r.stderr


def test_revived_guard_blocks_renamed_branch_revival(tmp_path: Path) -> None:
    """로컬 X 를 원격 Y 로 올렸다가 Y 가 지워진 경우. upstream 은 push 대상(Y)을 가리킨다."""
    repo = _repo_with_remote(tmp_path)
    _git(repo, "switch", "-qc", "feat/x")
    _commit(repo, "x\n", "c1")
    _git(repo, "push", "-u", "origin", "feat/x:feat/y")
    _git(repo, "push", "origin", "--delete", "feat/y")
    _commit(repo, "y\n", "c2")

    r = _git(repo, "push", "origin", "feat/x:feat/y", check=False)

    assert r.returncode != 0
    assert "원격에서 사라진 브랜치" in r.stderr


def test_revived_guard_allows_first_push_to_another_remote(tmp_path: Path) -> None:
    """upstream 이 origin 인 브랜치를 fork 로 처음 올리는 것은 부활이 아니다."""
    repo = _repo_with_remote(tmp_path, extra_remotes=("fork",))
    _git(repo, "switch", "-qc", "feat/x")
    _commit(repo, "x\n", "c1")
    _git(repo, "push", "-u", "origin", "feat/x")
    _commit(repo, "y\n", "c2")

    r = _git(repo, "push", "fork", "feat/x", check=False)

    assert r.returncode == 0, r.stderr


def test_revived_guard_hint_unsets_upstream_instead_of_no_verify(tmp_path: Path) -> None:
    """--no-verify 는 같은 훅의 다른 검사(lint·test)까지 건너뛴다. 안내는 upstream 만
    지우게 하고, 그 명령을 그대로 실행하면 push 가 성공해야 한다."""
    repo = _repo_with_remote(tmp_path)
    _git(repo, "switch", "-qc", "feat/x")
    _commit(repo, "x\n", "c1")
    _git(repo, "push", "-u", "origin", "feat/x")
    _git(repo, "push", "origin", "--delete", "feat/x")
    _commit(repo, "y\n", "c2")

    r = _git(repo, "push", "origin", "HEAD", check=False)

    assert "--no-verify" not in r.stderr
    hint = re.search(r"의도한 것이라면 : (.+)", r.stderr)
    assert hint, r.stderr
    cmd = hint.group(1).strip()
    assert cmd == "git branch --unset-upstream feat/x && git push -u origin feat/x"
    done = subprocess.run(cmd, shell=True, cwd=repo, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_dev_hook_sot_embeds_current_guard_block() -> None:
    """`scripts/hooks/pre-push.sh` 의 임베드 블록은 render_guard_block 출력과 byte-identical.

    두 설치 경로(install-git-hooks.sh ↔ anvyc guard install)가 같은 pre-push 를 두고
    서로 덮어쓰지 않도록 SoT 가 가드를 품는 구조다. render 를 고치고 SoT 를 안 고치면
    재설치 순서에 따라 가드가 조용히 옛 버전으로 되돌아간다.
    """
    sot = Path(__file__).resolve().parents[2] / "scripts" / "hooks" / "pre-push.sh"
    text = sot.read_text(encoding="utf-8")
    expected = render_guard_block(_POLICY)

    start = text.index(GUARD_BEGIN)
    end = text.index(GUARD_END) + len(GUARD_END) + 1  # 마커 줄의 개행까지

    assert text[start:end] == expected
