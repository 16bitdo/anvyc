"""tests/unit/test_conftest_git_env_isolation.py — 테스트의 git 명령이 물려받은 저장소로 새지 않는다.

#222 는 pre-push 게이트 경로만 막았다. pytest 자체가 git 저장소-지역 환경변수를 물려받는 경로는 그대로다 —
linked worktree 에서 git 이 띄운 명령은 그 worktree 의 절대 `GIT_DIR` 을 받는다: pre-commit·pre-push·
post-checkout 훅, `rebase -x`, `bisect run`, `!` alias(2026-10-01 샌드박스 실측, 일반 체크아웃에서는 없음).
pre-commit 은 절대 `GIT_INDEX_FILE` 까지 받는다. 그 아래에서 픽스처가 `git -C <tmp> …` 를 하면 `-C` 는
cwd 만 바꾸고 절대 경로 변수가 이긴다 — 2026-10-01 에 공용 `.git/config` 에 `core.bare=true`·`user.*`·
`core.hooksPath` 가 써졌고, 같은 경로로 `commit` 은 그 worktree 의 브랜치에, `add` 는 그 인덱스에 쓴다.

샌드박스(tmp_path)에 저장소와 linked worktree 를 만들고, linked worktree 의 pre-commit 훅이 받는 두 변수를
심은 환경으로 pytest 를 다시 띄워 아래 probe 를 돌린다. 샌드박스의 공용 config·브랜치·인덱스가 그대로인지
단언한다. 재현은 반드시 버리는 샌드박스로 한다 — 실제 gitdir 로 재현하면 실제 저장소가 오염된다.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROBE = "test_fixture_git_stays_in_its_tmp_repo"


def _clean_env(home: Path) -> dict[str, str]:
    """`GIT_*` 를 전부 지우고 전역·시스템 git 설정을 끊은 환경."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        {
            "HOME": str(home),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
    )
    return env


def _git(env: dict[str, str] | None, *args: str) -> str:
    return subprocess.run(
        ["git", *args], env=env, capture_output=True, text=True, check=True
    ).stdout.strip()


def test_fixture_git_stays_in_its_tmp_repo(tmp_path: Path) -> None:
    """픽스처식 git 명령은 자기 임시 저장소에만 쓴다 — 아래 테스트가 누수 환경으로 다시 띄우는 probe.

    사고 때의 픽스처처럼 상속 환경 그대로(env 미지정) git 을 부른다.
    """
    repo = tmp_path / "fixture"
    _git(None, "init", "-q", "-b", "main", str(repo))
    _git(None, "-C", str(repo), "config", "core.hooksPath", "scripts/hooks")
    (repo / "f").write_text("f\n", encoding="utf-8")
    _git(None, "-C", str(repo), "add", "f")
    _git(None, "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "probe")

    own_config = repo / ".git" / "config"
    assert _git(None, "config", "--file", str(own_config), "--get", "core.hooksPath") == "scripts/hooks"
    assert _git(None, "-C", str(repo), "log", "--format=%s") == "probe"


def test_pytest_under_leaked_worktree_git_env_leaves_that_repo_untouched(tmp_path: Path) -> None:
    env = _clean_env(tmp_path)
    repo = tmp_path / "repo"
    wt = tmp_path / "wt"
    _git(env, "init", "-q", "-b", "main", str(repo))
    (repo / "a").write_text("a\n", encoding="utf-8")
    _git(env, "-C", str(repo), "add", "a")
    _git(env, "-C", str(repo), "commit", "-qm", "base")
    _git(env, "-C", str(repo), "worktree", "add", "-q", "-b", "feat/x", str(wt))

    gitdir = repo / ".git" / "worktrees" / "wt"
    leaked = {**env, "GIT_DIR": str(gitdir), "GIT_INDEX_FILE": str(gitdir / "index")}
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"{__file__}::{PROBE}"],
        cwd=ROOT, env=leaked, capture_output=True, text=True, timeout=120,
    )
    # 0(통과)·1(실패) 만 probe 가 실제로 돌았다는 뜻 — 수집 실패·0건이면 아래 피해 단언이 공허해진다
    assert run.returncode in (0, 1), run.stdout + run.stderr

    common = repo / ".git" / "config"
    assert _git(env, "config", "--file", str(common), "--get", "core.bare") == "false"
    assert "hooksPath" not in common.read_text(encoding="utf-8")
    assert _git(env, "-C", str(repo), "log", "--format=%s", "feat/x") == "base"
    assert _git(env, "-C", str(wt), "ls-files") == "a"  # 인덱스 — GIT_INDEX_FILE 누수의 피해
    assert run.returncode == 0, run.stdout + run.stderr


def test_conftest_loads_without_git(tmp_path: Path) -> None:
    """git 이 없으면 지울 것도 없다 — 부를 git 이 없으니 샐 곳도 없다. conftest 오류로 스위트 전체를 막지 않는다."""
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", __file__],
        cwd=ROOT, env={**_clean_env(tmp_path), "PATH": str(empty_bin)},
        capture_output=True, text=True, timeout=120,
    )
    assert run.returncode == 0, run.stdout + run.stderr
