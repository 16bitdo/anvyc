"""anvyc gh_route 단위 테스트 (race-immune account 라우팅)."""
from __future__ import annotations

import textwrap
from pathlib import Path

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
