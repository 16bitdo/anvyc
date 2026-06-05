"""anvyc project_init 순수 로직 단위 테스트."""
from __future__ import annotations

from anvyc.core.project_info import _derive_gh_account, gh_config_dir_for_account


def test_gh_config_dir_for_account() -> None:
    assert gh_config_dir_for_account("16bitdo") == "$HOME/.config/gh-16bitdo"
    assert gh_config_dir_for_account("heisgone") == "$HOME/.config/gh-heisgone"


def test_gh_config_dir_round_trips_with_derive() -> None:
    assert _derive_gh_account(gh_config_dir_for_account("heisgone")) == "heisgone"
