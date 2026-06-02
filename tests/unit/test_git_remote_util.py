"""git_remote utility 단위 테스트 (P4, v0.8.0)."""
from __future__ import annotations

import textwrap
from pathlib import Path

from anvyc.utils.git_remote import origin_owner_repo, parse_git_config, to_dict


def _write_git_config(git_dir: Path, body: str) -> None:
    git_dir.mkdir(parents=True, exist_ok=True)
    (git_dir / "config").write_text(textwrap.dedent(body))


def test_ssh_remote_origin(tmp_path: Path) -> None:
    g = tmp_path / ".git"
    _write_git_config(
        g,
        """\
        [core]
            repositoryformatversion = 0
        [remote "origin"]
            url = git@github.com:acme/widgets.git
            fetch = +refs/heads/*:refs/remotes/origin/*
        """,
    )
    out = parse_git_config(g)
    assert len(out) == 1
    r = out[0]
    assert r.name == "origin"
    assert r.host == "github.com"
    assert r.owner == "acme"
    assert r.repo == "widgets"
    assert r.ssh_alias is None
    assert r.protocol == "ssh"


def test_ssh_with_alias(tmp_path: Path) -> None:
    g = tmp_path / ".git"
    _write_git_config(
        g,
        """\
        [remote "origin"]
            url = git@github.com-16bitdo:16bitdo/anvyc.git
        """,
    )
    out = parse_git_config(g)
    assert len(out) == 1
    assert out[0].host == "github.com-16bitdo"
    assert out[0].ssh_alias == "16bitdo"
    assert out[0].owner == "16bitdo"


def test_https_remote(tmp_path: Path) -> None:
    g = tmp_path / ".git"
    _write_git_config(
        g,
        """\
        [remote "origin"]
            url = https://github.com/acme/widgets
        """,
    )
    out = parse_git_config(g)
    assert len(out) == 1
    assert out[0].protocol == "https"
    assert out[0].host == "github.com"
    assert out[0].repo == "widgets"


def test_multi_remote(tmp_path: Path) -> None:
    g = tmp_path / ".git"
    _write_git_config(
        g,
        """\
        [remote "origin"]
            url = git@github.com:acme/fork.git
        [remote "upstream"]
            url = git@github.com:upstream-owner/parent.git
        """,
    )
    out = parse_git_config(g)
    names = sorted(r.name for r in out)
    assert names == ["origin", "upstream"]


def test_non_github_host(tmp_path: Path) -> None:
    """gitlab/bitbucket 도 host 그대로 보존."""
    g = tmp_path / ".git"
    _write_git_config(
        g,
        """\
        [remote "origin"]
            url = git@gitlab.com:group/proj.git
        """,
    )
    out = parse_git_config(g)
    assert len(out) == 1
    assert out[0].host == "gitlab.com"
    assert out[0].ssh_alias is None


def test_missing_git_config(tmp_path: Path) -> None:
    out = parse_git_config(tmp_path / "nonexistent" / ".git")
    assert out == []


def test_invalid_url_skipped(tmp_path: Path) -> None:
    """일부 remote 가 unrecognized URL → 그 항목만 skip, 나머지는 보존."""
    g = tmp_path / ".git"
    _write_git_config(
        g,
        """\
        [remote "origin"]
            url = unknown://format
        [remote "good"]
            url = git@github.com:a/b.git
        """,
    )
    out = parse_git_config(g)
    assert len(out) == 1
    assert out[0].name == "good"


def test_to_dict_schema(tmp_path: Path) -> None:
    g = tmp_path / ".git"
    _write_git_config(g, '[remote "origin"]\n    url = git@github.com:a/b.git\n')
    out = parse_git_config(g)
    d = to_dict(out[0])
    assert set(d.keys()) == {"name", "url", "host", "owner", "repo", "ssh_alias", "protocol"}


# ---------------------------------------------------------------------------
# origin_owner_repo tests
# ---------------------------------------------------------------------------

def test_origin_owner_repo_ssh_alias(tmp_path: Path) -> None:
    """ssh alias origin git@github.com-16bitdo:owner/repo.git → ('owner', 'repo')."""
    _write_git_config(
        tmp_path / ".git",
        """\
        [remote "origin"]
            url = git@github.com-16bitdo:owner/repo.git
        """,
    )
    assert origin_owner_repo(tmp_path) == ("owner", "repo")


def test_origin_owner_repo_no_origin(tmp_path: Path) -> None:
    """origin remote 없음(또는 .git 없음) → None."""
    # No .git directory at all — parse_git_config returns []
    assert origin_owner_repo(tmp_path) is None
