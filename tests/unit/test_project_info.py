"""core.project_info 의 derive/expand 헬퍼 단위 테스트.

`_derive_claude_account` (v0.12.0, Claude 계정 라우팅) 및 공용 헬퍼
`expand_envrc_path` 검증.
"""

from __future__ import annotations

from pathlib import Path

from anvyc.core.project_info import _derive_claude_account, expand_envrc_path


class TestDeriveClaudeAccount:
    def test_dot_claude_prefix_strips_to_account(self) -> None:
        assert _derive_claude_account("$HOME/.claude-edward") == "edward"
        assert _derive_claude_account("/Users/edward/.claude-jklee") == "jklee"

    def test_claude_prefix_without_dot(self) -> None:
        assert _derive_claude_account("$HOME/claude-bot") == "bot"

    def test_trailing_slash_tolerated(self) -> None:
        assert _derive_claude_account("$HOME/.claude-edward/") == "edward"

    def test_default_claude_dir_yields_none(self) -> None:
        """suffix 없는 기본 `~/.claude` 는 라우팅 계정 없음 → None."""
        assert _derive_claude_account("$HOME/.claude") is None

    def test_non_convention_path_yields_none(self) -> None:
        assert _derive_claude_account("/opt/some/other/path") is None

    def test_empty_or_none_yields_none(self) -> None:
        assert _derive_claude_account(None) is None
        assert _derive_claude_account("") is None


class TestExpandEnvrcPath:
    def test_expands_dollar_home(self) -> None:
        assert expand_envrc_path("$HOME/.claude-x") == Path.home() / ".claude-x"

    def test_expands_braced_home(self) -> None:
        assert expand_envrc_path("${HOME}/.claude-x") == Path.home() / ".claude-x"

    def test_expands_tilde(self) -> None:
        assert expand_envrc_path("~/.claude-x") == Path.home() / ".claude-x"

    def test_absolute_path_unchanged(self) -> None:
        assert expand_envrc_path("/abs/claude-x") == Path("/abs/claude-x")
