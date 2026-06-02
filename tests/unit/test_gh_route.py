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
