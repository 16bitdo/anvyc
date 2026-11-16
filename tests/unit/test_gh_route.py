"""anvyc gh_route 단위 테스트 (race-immune account 라우팅)."""
from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest

from anvyc.core import gh_route


def _write_git_config(repo: Path, body: str) -> Path:
    g = repo / ".git"
    g.mkdir(parents=True, exist_ok=True)
    (g / "config").write_text(textwrap.dedent(body))
    return repo


def test_resolve_account_from_ssh_alias(tmp_path: Path) -> None:
    repo = _write_git_config(tmp_path, """\
        [remote "origin"]
            url = git@github.com-16bitdo:16bitdo/anvyc.git
    """)
    assert gh_route.resolve_account(repo) == "16bitdo"


def test_resolve_account_heisgone_org_repo(tmp_path: Path) -> None:
    repo = _write_git_config(tmp_path, """\
        [remote "origin"]
            url = git@github.com-heisgone:whatap/open-scripts.git
    """)
    assert gh_route.resolve_account(repo) == "heisgone"


def test_resolve_account_none_for_plain_remote(tmp_path: Path) -> None:
    repo = _write_git_config(tmp_path, """\
        [remote "origin"]
            url = https://github.com/owner/x.git
    """)
    assert gh_route.resolve_account(repo) is None


def test_resolve_account_none_without_origin(tmp_path: Path) -> None:
    repo = _write_git_config(tmp_path, """\
        [remote "upstream"]
            url = git@github.com-16bitdo:16bitdo/x.git
    """)
    assert gh_route.resolve_account(repo) is None


def test_resolve_account_walks_up_from_subdir(tmp_path: Path) -> None:
    repo = _write_git_config(tmp_path, """\
        [remote "origin"]
            url = git@github.com-16bitdo:16bitdo/anvyc.git
    """)
    sub = repo / "src" / "deep"
    sub.mkdir(parents=True)
    assert gh_route.resolve_account(sub) == "16bitdo"


def test_resolve_account_none_when_no_git(tmp_path: Path) -> None:
    assert gh_route.resolve_account(tmp_path) is None


def _make_linked_worktree(wt: Path, main: Path, url: str) -> Path:
    """`main`(origin=url) 의 linked worktree 를 `wt` 에 실측 레이아웃대로 만든다 — git 프로세스 없이.

    `wt/.git` 은 `gitdir: <main/.git/worktrees/<name>>` 포인터 파일이고, 그 사설 gitdir 의
    `commondir` 이 `../..`(본체 `.git`)를 가리킨다(test_project_info_worktree.py 와 같은 실측).
    """
    _write_git_config(main, f"""\
        [remote "origin"]
            url = {url}
    """)
    private = main / ".git" / "worktrees" / wt.name
    private.mkdir(parents=True)
    (private / "commondir").write_text("../..\n")
    wt.mkdir(parents=True)
    (wt / ".git").write_text(f"gitdir: {private}\n")
    return wt


def test_resolve_account_from_linked_worktree_subdir(tmp_path: Path) -> None:
    """worktree 의 `.git` 은 디렉터리가 아니라 포인터 파일 — 본체 config 의 origin 으로 도출한다."""
    wt = _make_linked_worktree(
        tmp_path / "worktrees" / "feat", tmp_path / "main",
        "git@github.com-16bitdo:16bitdo/anvyc.git",
    )
    sub = wt / "src"
    sub.mkdir()
    assert gh_route.resolve_account(sub) == "16bitdo"


def test_resolve_account_worktree_inside_other_repo_uses_its_own_origin(tmp_path: Path) -> None:
    """다른 저장소 안에 놓인 worktree — `.git` 파일을 건너뛰고 올라가면 바깥 저장소의 계정
    토큰을 주입하게 된다(2026-11-16 재현: 'work' 로 잘못 라우팅)."""
    outer = _write_git_config(tmp_path / "outer", """\
        [remote "origin"]
            url = git@github.com-work:acme/other.git
    """)
    wt = _make_linked_worktree(
        outer / "nested-wt", tmp_path / "main",
        "git@github.com-16bitdo:16bitdo/anvyc.git",
    )
    assert gh_route.resolve_account(wt) == "16bitdo"


def test_resolve_account_broken_worktree_pointer_does_not_climb(tmp_path: Path) -> None:
    """포인터가 깨진 worktree 는 None — 바깥 저장소 계정으로 대신 라우팅하지 않는다.
    git 도 처음 만난 `.git` 에서 멈추고 더 올라가지 않는다."""
    outer = _write_git_config(tmp_path / "outer", """\
        [remote "origin"]
            url = git@github.com-work:acme/other.git
    """)
    wt = outer / "stale-wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {tmp_path / 'gone'}\n")
    assert gh_route.resolve_account(wt) is None


def test_resolve_account_survives_multivalued_key(tmp_path: Path) -> None:
    """다중값 키가 있는 저장소에서도 계정을 도출해야 한다.

    2026-11-12 `anvyc gh` 가 "account 를 도출할 수 없습니다" 로 실패한 원인 —
    parse_git_config 가 DuplicateOptionError 를 삼키고 [] 를 돌려줬다.
    """
    repo = _write_git_config(tmp_path, """\
        [remote "origin"]
            url = git@github.com-secondary:acme/widgets.git
        [personal-config-guard]
            allow = templates/dev.env.config
            allow = templates/prod.env.config
    """)
    assert gh_route.resolve_account(repo) == "secondary"


def test_token_for_returns_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        assert cmd == ["gh", "auth", "token", "--user", "16bitdo"]
        return subprocess.CompletedProcess(cmd, 0, stdout="ghp_FAKE\n", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert gh_route._token_for("16bitdo") == "ghp_FAKE"


def test_token_for_raises_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="not logged in")
    monkeypatch.setattr(subprocess, "run", fake_run)
    try:
        gh_route._token_for("nobody")
        raise AssertionError("expected GhRouteError")
    except gh_route.GhRouteError as e:
        assert "nobody" in str(e)


def test_run_gh_injects_token_and_passes_args(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        calls.append((cmd, kw))
        if cmd[:3] == ["gh", "auth", "token"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="ghp_FAKE\n", stderr="")
        return subprocess.CompletedProcess(cmd, 7, stdout="", stderr="")  # gh exec exit code

    monkeypatch.setattr(subprocess, "run", fake_run)

    code = gh_route.run_gh("16bitdo", ["pr", "create", "--title", "x"])

    assert code == 7
    assert calls[0][0] == ["gh", "auth", "token", "--user", "16bitdo"]
    exec_cmd, exec_kw = calls[1]
    assert exec_cmd == ["gh", "pr", "create", "--title", "x"]
    env = exec_kw["env"]
    assert isinstance(env, dict)
    assert env["GH_TOKEN"] == "ghp_FAKE"  # 토큰 env 주입
    assert not exec_kw.get("capture_output")  # stdio passthrough
