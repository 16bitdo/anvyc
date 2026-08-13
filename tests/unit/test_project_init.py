"""anvyc project_init 순수 로직 단위 테스트."""
from __future__ import annotations

import textwrap
from pathlib import Path

from anvyc.core.project_info import derive_gh_account, gh_config_dir_for_account
from anvyc.core.project_init import (
    ensure_gitignore_entry,
    gh_account_logged_in,
    resolve_routing_account,
    write_envrc_gh_routing,
)


def test_gh_config_dir_for_account() -> None:
    assert gh_config_dir_for_account("16bitdo") == "$HOME/.config/gh-16bitdo"
    assert gh_config_dir_for_account("heisgone") == "$HOME/.config/gh-heisgone"


def test_gh_config_dir_round_trips_with_derive() -> None:
    assert derive_gh_account(gh_config_dir_for_account("heisgone")) == "heisgone"


# ---------------------------------------------------------------------------
# Task 3: write_envrc_gh_routing
# ---------------------------------------------------------------------------


def test_write_envrc_creates_new_file(tmp_path: Path) -> None:
    envrc = tmp_path / ".envrc"
    status = write_envrc_gh_routing(envrc, "16bitdo")
    assert status == "created"
    assert envrc.read_text() == 'export GH_CONFIG_DIR="$HOME/.config/gh-16bitdo"\n'


def test_write_envrc_replaces_different_value(tmp_path: Path) -> None:
    envrc = tmp_path / ".envrc"
    envrc.write_text('export GH_CONFIG_DIR="$HOME/.config/gh-none"\n')
    status = write_envrc_gh_routing(envrc, "16bitdo")
    assert status == "replaced"
    assert envrc.read_text() == 'export GH_CONFIG_DIR="$HOME/.config/gh-16bitdo"\n'


def test_write_envrc_unchanged_when_same(tmp_path: Path) -> None:
    envrc = tmp_path / ".envrc"
    envrc.write_text('export GH_CONFIG_DIR="$HOME/.config/gh-16bitdo"\n')
    assert write_envrc_gh_routing(envrc, "16bitdo") == "unchanged"


def test_write_envrc_replaced_preserves_surrounding_and_midfile(tmp_path: Path) -> None:
    envrc = tmp_path / ".envrc"
    envrc.write_text(
        'export AWS_PROFILE="dev"\n'
        'export GH_CONFIG_DIR="$HOME/.config/gh-old"\n'
        'export FOO=bar\n'
    )
    assert write_envrc_gh_routing(envrc, "16bitdo") == "replaced"
    assert envrc.read_text() == (
        'export AWS_PROFILE="dev"\n'
        'export GH_CONFIG_DIR="$HOME/.config/gh-16bitdo"\n'
        'export FOO=bar\n'
    )


def test_write_envrc_replaced_normalizes_trailing_newline(tmp_path: Path) -> None:
    envrc = tmp_path / ".envrc"
    envrc.write_text('export GH_CONFIG_DIR="$HOME/.config/gh-old"')  # no trailing newline
    assert write_envrc_gh_routing(envrc, "16bitdo") == "replaced"
    assert envrc.read_text() == 'export GH_CONFIG_DIR="$HOME/.config/gh-16bitdo"\n'


def test_write_envrc_adds_to_existing_preserving_others(tmp_path: Path) -> None:
    envrc = tmp_path / ".envrc"
    envrc.write_text('export AWS_PROFILE="dev"\n')
    status = write_envrc_gh_routing(envrc, "16bitdo")
    assert status == "added"
    body = envrc.read_text()
    assert 'export AWS_PROFILE="dev"' in body
    assert 'export GH_CONFIG_DIR="$HOME/.config/gh-16bitdo"' in body


# ---------------------------------------------------------------------------
# Task 4: ensure_gitignore_entry
# ---------------------------------------------------------------------------


def test_gitignore_created_when_absent(tmp_path: Path) -> None:
    gi = tmp_path / ".gitignore"
    assert ensure_gitignore_entry(gi, ".envrc") is True
    assert gi.read_text() == ".envrc\n"


def test_gitignore_appends_when_missing_entry(tmp_path: Path) -> None:
    gi = tmp_path / ".gitignore"
    gi.write_text("node_modules/\n")
    assert ensure_gitignore_entry(gi, ".envrc") is True
    assert gi.read_text() == "node_modules/\n.envrc\n"


def test_gitignore_noop_when_present(tmp_path: Path) -> None:
    gi = tmp_path / ".gitignore"
    gi.write_text(".env\n.envrc\n")
    assert ensure_gitignore_entry(gi, ".envrc") is False
    assert gi.read_text() == ".env\n.envrc\n"


# ---------------------------------------------------------------------------
# Task 5: resolve_routing_account
# ---------------------------------------------------------------------------


def _repo(tmp_path: Path, url: str) -> Path:
    g = tmp_path / ".git"
    g.mkdir(parents=True, exist_ok=True)
    (g / "config").write_text(textwrap.dedent(f"""\
        [remote "origin"]
            url = {url}
    """))
    return tmp_path


def test_resolve_account_from_alias(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "git@github.com-16bitdo:16bitdo/x.git")
    assert resolve_routing_account(repo, {}) == ("16bitdo", "alias")


def test_resolve_account_from_mapping_when_plain_host(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "https://github.com/whatap/x.git")
    assert resolve_routing_account(repo, {"whatap": "heisgone"}) == ("heisgone", "mapping")


def test_resolve_account_unknown_plain_host_no_mapping(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "https://github.com/acme/x.git")
    assert resolve_routing_account(repo, {"whatap": "heisgone"}) == (None, "unknown")


def test_resolve_account_unknown_when_no_remote(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("")
    assert resolve_routing_account(tmp_path, {}) == (None, "unknown")


# ---------------------------------------------------------------------------
# Task 6: gh_account_logged_in
# ---------------------------------------------------------------------------


def test_logged_in_true_when_hosts_yml_exists(tmp_path: Path) -> None:
    (tmp_path / "gh-16bitdo").mkdir()
    (tmp_path / "gh-16bitdo" / "hosts.yml").write_text("github.com: {}\n")
    assert gh_account_logged_in("16bitdo", config_home=tmp_path) is True


def test_logged_in_false_when_absent(tmp_path: Path) -> None:
    assert gh_account_logged_in("none", config_home=tmp_path) is False
