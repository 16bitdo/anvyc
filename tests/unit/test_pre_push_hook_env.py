"""tests/unit/test_pre_push_hook_env.py — pre-push 게이트가 git 저장소-지역 환경변수를 물려주지 않는다.

git 은 훅에 저장소-지역 환경변수를 export 한다(githooks(5)). linked worktree 에서 push 하면 `GIT_DIR` 이
그 worktree 의 절대 gitdir 이다 — 일반 체크아웃에서는 export 되지 않는다(실측). 이것을 그대로 pytest 에
물려주면 테스트 픽스처의 `git -C <tmp> …` 가 임시 저장소가 아니라 push 하는 저장소를 건드린다: `-C` 는
cwd 만 바꾸고 절대 `GIT_DIR` 이 이긴다. 2026-10-01 에 공용 `.git/config` 에 `core.bare=true` · `user.*` ·
`core.hooksPath` 가 써졌다.

샌드박스(tmp_path)에 원격·저장소·linked worktree 를 만들고 SoT 훅을 그 저장소의 pre-push 로 설치한 뒤
worktree 에서 push 한다. worktree 의 가짜 `.venv/bin/pytest` 는 받은 환경을 기록하고, 사고 때의 픽스처처럼
다른 경로에서 `git -C <tmp> init`·`config user.name` 을 한다 — 새어 들어간 `GIT_DIR` 아래에서 이 둘이
push 한 저장소의 공용 config 에 `core.bare=true`·`user.name` 을 쓴다(실측. `init --bare <경로>` 는 쓰지
않는다). 이 테스트 자신의 git 호출도 `GIT_*` 를 지운 환경으로 한다 — 어떤 훅 아래에서 돌아도 실제
저장소로 새지 않게.
"""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

HOOK_SOT = Path(__file__).resolve().parents[2] / "scripts" / "hooks" / "pre-push.sh"


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


def _git(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], env=env, capture_output=True, text=True, check=True)


def _executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def test_gate_does_not_pass_repo_local_git_env_on_worktree_push(tmp_path: Path) -> None:
    env = _clean_env(tmp_path)
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    wt = tmp_path / "wt"
    probe = tmp_path / "probe"
    probe.mkdir()
    _git(env, "init", "-q", "--bare", "-b", "main", str(remote))
    _git(env, "init", "-q", "-b", "main", str(repo))
    (repo / "a").write_text("a\n", encoding="utf-8")
    _git(env, "-C", str(repo), "add", "a")
    _git(env, "-C", str(repo), "commit", "-qm", "a")
    _git(env, "-C", str(repo), "remote", "add", "origin", str(remote))
    _git(env, "-C", str(repo), "push", "-q", "origin", "main")  # 훅 설치 전 — 기준점
    _executable(repo / ".git" / "hooks" / "pre-push", HOOK_SOT.read_text(encoding="utf-8"))

    _git(env, "-C", str(repo), "worktree", "add", "-q", "-b", "feat/x", str(wt))
    venv = wt / ".venv" / "bin"
    venv.mkdir(parents=True)
    for tool in ("ruff", "mypy"):
        _executable(venv / tool, "#!/bin/sh\nexit 0\n")
    _executable(
        venv / "pytest",
        "#!/bin/sh\n"
        f"env | grep '^GIT_' > '{probe}/pytest.env'\n"
        f"mkdir -p '{probe}/fixture'\n"
        f"git -C '{probe}/fixture' init -q\n"
        f"git -C '{probe}/fixture' config user.name leaked\n",
    )
    (wt / "b").write_text("b\n", encoding="utf-8")
    _git(env, "-C", str(wt), "add", "b")
    _git(env, "-C", str(wt), "commit", "-qm", "b")

    push = subprocess.run(
        ["git", "-C", str(wt), "push", "-q", "origin", "feat/x"],
        env=env, capture_output=True, text=True,
    )
    assert push.returncode == 0, push.stderr
    recorded = probe / "pytest.env"
    assert recorded.is_file(), "게이트의 pytest 단계가 돌지 않았다 — 아래 부재 단언이 공허해진다"

    local_vars = set(_git(env, "rev-parse", "--local-env-vars").stdout.split())
    passed = sorted(
        name
        for name in (line.split("=", 1)[0] for line in recorded.read_text(encoding="utf-8").splitlines())
        if name in local_vars
    )
    assert passed == []
    # 사고의 실제 피해 — 픽스처의 git 명령이 push 한 저장소의 공용 config 에 쓰지 않았다
    common = repo / ".git" / "config"
    assert _git(env, "config", "--file", str(common), "--get", "core.bare").stdout.strip() == "false"
    assert "leaked" not in common.read_text(encoding="utf-8")
