"""core.project_info 의 derive/expand 헬퍼 단위 테스트.

`_derive_claude_account` (v0.12.0, Claude 계정 라우팅) 및 공용 헬퍼
`expand_envrc_path` 검증.
"""

from __future__ import annotations

from pathlib import Path

from anvyc.core.project_info import (
    _derive_claude_account,
    expand_envrc_path,
    resolve_cwd_aws_profiles,
)


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


class TestResolveCwdAwsProfiles:
    """creds-expiry project-scope (2026-05-31) — cwd walk-up → 프로젝트 AWS profile."""

    def test_envrc_with_aws_profile(self, tmp_path: Path) -> None:
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / ".envrc").write_text("export AWS_PROFILE=dev\n", encoding="utf-8")
        assert resolve_cwd_aws_profiles(proj) == frozenset({"dev"})

    def test_nested_subdir_finds_nearest_boundary(self, tmp_path: Path) -> None:
        proj = tmp_path / "proj"
        (proj / "a" / "b").mkdir(parents=True)
        (proj / ".envrc").write_text('export AWS_PROFILE="prd"\n', encoding="utf-8")
        assert resolve_cwd_aws_profiles(proj / "a" / "b") == frozenset({"prd"})

    def test_git_project_without_envrc_is_empty(self, tmp_path: Path) -> None:
        """.git 경계 있으나 .envrc 없음(도구 repo) → frozenset() → aws_sso silent."""
        proj = tmp_path / "tool"
        (proj / ".git").mkdir(parents=True)
        assert resolve_cwd_aws_profiles(proj) == frozenset()

    def test_envrc_without_aws_profile_is_empty(self, tmp_path: Path) -> None:
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / ".envrc").write_text("export FOO=bar\n", encoding="utf-8")
        assert resolve_cwd_aws_profiles(proj) == frozenset()

    def test_no_project_boundary_is_empty(self, tmp_path: Path) -> None:
        bare = tmp_path / "bare"
        bare.mkdir()
        assert resolve_cwd_aws_profiles(bare) == frozenset()

    def test_nearer_git_project_shadows_outer_envrc(self, tmp_path: Path) -> None:
        """상위 .envrc(다른 프로젝트)를 안쪽 .git 프로젝트가 상속하지 않는다."""
        outer = tmp_path / "outer"
        inner = outer / "inner"
        inner.mkdir(parents=True)
        (outer / ".envrc").write_text("export AWS_PROFILE=outer-prof\n", encoding="utf-8")
        (inner / ".git").mkdir()
        assert resolve_cwd_aws_profiles(inner) == frozenset()
