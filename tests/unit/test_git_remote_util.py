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
# git config 문법 호환 — git config 는 INI 가 아니다
#
# 2026-11-12 실측: 한 조직 저장소의 .git/config 에 `[personal-config-guard]` 의
# `allow` 가 두 줄 있었다. git 은 한 키에 여러 값을 허용하지만, 엄격 모드
# RawConfigParser 는 DuplicateOptionError 를 던지고 parse_git_config 가 그것을
# 삼켜 원격 목록을 [] 로 돌려줬다. `anvyc gh` 는 "account 를 도출할 수 없습니다" 로
# 실패했고, 같은 함수를 쓰는 doctor check 들은 그 저장소를 경고 없이 건너뛰었다.
# 아래 설정은 모두 git 이 정상으로 읽는다(`git config --file <path> --list` 통과).
# ---------------------------------------------------------------------------


def test_multivalued_key_in_other_section_keeps_remotes(tmp_path: Path) -> None:
    """remote 와 무관한 섹션의 다중값 키 때문에 원격을 잃으면 안 된다 (2026-11-12 사례)."""
    g = tmp_path / ".git"
    _write_git_config(
        g,
        """\
        [remote "origin"]
            url = git@github.com-secondary:acme/widgets.git
            fetch = +refs/heads/*:refs/remotes/origin/*
        [personal-config-guard]
            allow = templates/dev.env.config
            allow = templates/prod.env.config
        """,
    )
    out = parse_git_config(g)
    assert [(r.name, r.ssh_alias, r.owner, r.repo) for r in out] == [
        ("origin", "secondary", "acme", "widgets")
    ]


def test_multivalued_fetch_refspec_in_remote_section(tmp_path: Path) -> None:
    """remote 섹션 안의 다중 fetch refspec(PR ref 까지 받는 흔한 설정)도 읽어야 한다."""
    g = tmp_path / ".git"
    _write_git_config(
        g,
        """\
        [remote "origin"]
            url = git@github.com:acme/widgets.git
            fetch = +refs/heads/*:refs/remotes/origin/*
            fetch = +refs/pull/*/head:refs/remotes/origin/pr/*
        """,
    )
    out = parse_git_config(g)
    assert len(out) == 1
    assert (out[0].name, out[0].owner, out[0].repo) == ("origin", "acme", "widgets")


def test_multiple_urls_uses_first_like_git(tmp_path: Path) -> None:
    """url 이 여러 개면 첫 번째를 쓴다 — `git remote get-url` 과 fetch 가 쓰는 값이다.

    INI 관례("나중 값이 이긴다")대로 고치면 두 번째(push 미러)를 잡아 이 테스트가 실패한다.
    git CLI 로 읽을 때도 함정이 있다 — `git config --get` 은 **마지막** 값을 돌려준다
    (실측). `--get-all` 의 첫 줄이어야 `git remote get-url` 과 같다.
    """
    g = tmp_path / ".git"
    _write_git_config(
        g,
        """\
        [remote "origin"]
            url = git@github.com:acme/widgets.git
            url = git@gitlab.com:mirror/widgets.git
        """,
    )
    out = parse_git_config(g)
    assert len(out) == 1
    assert out[0].host == "github.com"
    assert out[0].url == "git@github.com:acme/widgets.git"


def test_valueless_boolean_key_keeps_remotes(tmp_path: Path) -> None:
    """`=` 없는 키는 git 에서 boolean true 다(git-config(1)). INI 파서는 이것도 오류로 본다."""
    g = tmp_path / ".git"
    _write_git_config(
        g,
        """\
        [pull]
            rebase
        [remote "origin"]
            url = git@github.com:acme/widgets.git
        """,
    )
    out = parse_git_config(g)
    assert len(out) == 1
    assert out[0].owner == "acme"


def test_quoted_value_and_trailing_comment(tmp_path: Path) -> None:
    """값의 따옴표는 벗기고, 따옴표 밖 `#`·`;` 부터는 주석이다(git-config(1))."""
    g = tmp_path / ".git"
    _write_git_config(
        g,
        """\
        [remote "origin"]
            url = "git@github.com:acme/widgets.git"  # 사내 미러는 upstream
        [remote "upstream"]
            url = git@github.com:acme/parent.git ; 원본
        """,
    )
    out = parse_git_config(g)
    assert [(r.name, r.url) for r in out] == [
        ("origin", "git@github.com:acme/widgets.git"),
        ("upstream", "git@github.com:acme/parent.git"),
    ]


def test_section_and_key_names_are_case_insensitive(tmp_path: Path) -> None:
    """섹션·키 이름은 대소문자를 가리지 않고, 서브섹션(remote 이름)은 가린다."""
    g = tmp_path / ".git"
    _write_git_config(
        g,
        """\
        [Remote "Origin"]
            URL = git@github.com:acme/widgets.git
        """,
    )
    out = parse_git_config(g)
    assert [(r.name, r.repo) for r in out] == [("Origin", "widgets")]


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
