"""utils/gh_hosts.py 단위 테스트 (CP-13 PR-13D)."""

from __future__ import annotations

from pathlib import Path

import pytest

from anvyc.utils.gh_hosts import (
    GhAccount,
    discover_gh_accounts,
    discover_gh_config_dirs,
    parse_hosts_yml,
    select_config_dir_for_user,
)


def _write_hosts(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_parse_hosts_yml_4_space_indent(tmp_path: Path) -> None:
    """gh CLI 신버전 (4-space indent) 형식 인식."""
    hosts = tmp_path / "hosts.yml"
    _write_hosts(
        hosts,
        "github.com:\n"
        "    git_protocol: ssh\n"
        "    users:\n"
        "        16bitdo:\n"
        "        heisgone:\n"
        "    user: 16bitdo\n",
    )
    result = parse_hosts_yml(hosts)
    assert result == {"github.com": ["16bitdo", "heisgone"]}


def test_parse_hosts_yml_2_space_indent(tmp_path: Path) -> None:
    """gh CLI 1.x (2-space indent) 형식 인식."""
    hosts = tmp_path / "hosts.yml"
    _write_hosts(
        hosts,
        "github.com:\n"
        "  git_protocol: ssh\n"
        "  users:\n"
        "    16bitdo:\n"
        "    heisgone:\n"
        "  user: 16bitdo\n",
    )
    result = parse_hosts_yml(hosts)
    assert result == {"github.com": ["16bitdo", "heisgone"]}


def test_parse_hosts_yml_multi_host(tmp_path: Path) -> None:
    """github.com + 사내 ghe.example.com 같은 multi-host."""
    hosts = tmp_path / "hosts.yml"
    _write_hosts(
        hosts,
        "github.com:\n"
        "    users:\n"
        "        u1:\n"
        "ghe.example.com:\n"
        "    users:\n"
        "        u2:\n"
        "        u3:\n",
    )
    result = parse_hosts_yml(hosts)
    assert result == {"github.com": ["u1"], "ghe.example.com": ["u2", "u3"]}


def test_parse_hosts_yml_missing_file(tmp_path: Path) -> None:
    assert parse_hosts_yml(tmp_path / "noexist.yml") == {}


def test_parse_hosts_yml_empty(tmp_path: Path) -> None:
    hosts = tmp_path / "hosts.yml"
    _write_hosts(hosts, "")
    assert parse_hosts_yml(hosts) == {}


def test_discover_gh_config_dirs(tmp_path: Path) -> None:
    """`~/.config/gh*` glob 의 dir 만 발견."""
    (tmp_path / "gh").mkdir()
    (tmp_path / "gh-16bitdo").mkdir()
    (tmp_path / "gh-heisgone").mkdir()
    (tmp_path / "other").mkdir()  # gh* 아님
    (tmp_path / "gh-stray-file").write_text("not a dir")
    dirs = discover_gh_config_dirs(tmp_path)
    assert [d.name for d in dirs] == ["gh", "gh-16bitdo", "gh-heisgone"]


def test_discover_gh_config_dirs_missing_home(tmp_path: Path) -> None:
    assert discover_gh_config_dirs(tmp_path / "noexist") == []


def test_discover_gh_accounts_multi_dir(tmp_path: Path) -> None:
    """3 dir × 동일 hosts.yml 시 user×dir 모든 tuple 반환."""
    for cfg in ["gh", "gh-16bitdo", "gh-heisgone"]:
        _write_hosts(
            tmp_path / cfg / "hosts.yml",
            "github.com:\n    users:\n        16bitdo:\n        heisgone:\n",
        )
    accounts = discover_gh_accounts(tmp_path)
    keys = sorted({(a.config_dir.name, a.user) for a in accounts})
    assert keys == [
        ("gh", "16bitdo"),
        ("gh", "heisgone"),
        ("gh-16bitdo", "16bitdo"),
        ("gh-16bitdo", "heisgone"),
        ("gh-heisgone", "16bitdo"),
        ("gh-heisgone", "heisgone"),
    ]
    assert all(isinstance(a, GhAccount) for a in accounts)


def test_select_config_dir_for_user_prefers_explicit(tmp_path: Path) -> None:
    """`gh-<user>` 분리 dir 우선."""
    for cfg in ["gh", "gh-16bitdo", "gh-heisgone"]:
        _write_hosts(
            tmp_path / cfg / "hosts.yml",
            "github.com:\n    users:\n        16bitdo:\n        heisgone:\n",
        )
    assert (
        select_config_dir_for_user("16bitdo", config_home=tmp_path)
        == tmp_path / "gh-16bitdo"
    )
    assert (
        select_config_dir_for_user("heisgone", config_home=tmp_path)
        == tmp_path / "gh-heisgone"
    )


def test_select_config_dir_for_user_falls_back_to_first(
    tmp_path: Path,
) -> None:
    """explicit `gh-<user>` 부재 시 첫 dir."""
    _write_hosts(
        tmp_path / "gh" / "hosts.yml",
        "github.com:\n    users:\n        16bitdo:\n",
    )
    assert (
        select_config_dir_for_user("16bitdo", config_home=tmp_path)
        == tmp_path / "gh"
    )


def test_select_config_dir_for_user_unknown(tmp_path: Path) -> None:
    _write_hosts(
        tmp_path / "gh" / "hosts.yml",
        "github.com:\n    users:\n        16bitdo:\n",
    )
    assert select_config_dir_for_user("noexist", config_home=tmp_path) is None


@pytest.mark.parametrize(
    "user_name", ["16bitdo", "heisgone", "user.with.dots", "user-with-dash"]
)
def test_parse_hosts_yml_user_name_chars(tmp_path: Path, user_name: str) -> None:
    """gh user 이름의 다양한 글자 (영문/숫자/`.`/`-`)."""
    hosts = tmp_path / "hosts.yml"
    _write_hosts(
        hosts,
        f"github.com:\n    users:\n        {user_name}:\n",
    )
    assert parse_hosts_yml(hosts) == {"github.com": [user_name]}
