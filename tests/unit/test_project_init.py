"""anvyc project_init 순수 로직 단위 테스트."""
from __future__ import annotations

import textwrap
from pathlib import Path

from anvyc.core.project_info import _derive_gh_account, gh_config_dir_for_account
from anvyc.core.project_init import write_envrc_gh_routing


def test_gh_config_dir_for_account() -> None:
    assert gh_config_dir_for_account("16bitdo") == "$HOME/.config/gh-16bitdo"
    assert gh_config_dir_for_account("heisgone") == "$HOME/.config/gh-heisgone"


def test_gh_config_dir_round_trips_with_derive() -> None:
    assert _derive_gh_account(gh_config_dir_for_account("heisgone")) == "heisgone"


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


def test_write_envrc_adds_to_existing_preserving_others(tmp_path: Path) -> None:
    envrc = tmp_path / ".envrc"
    envrc.write_text('export AWS_PROFILE="dev"\n')
    status = write_envrc_gh_routing(envrc, "16bitdo")
    assert status == "added"
    body = envrc.read_text()
    assert 'export AWS_PROFILE="dev"' in body
    assert 'export GH_CONFIG_DIR="$HOME/.config/gh-16bitdo"' in body
