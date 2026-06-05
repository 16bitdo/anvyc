"""anvyc project init CLI 동작 테스트 (CliRunner)."""
from __future__ import annotations

import textwrap
from pathlib import Path

from typer.testing import CliRunner

from anvyc.cli import app

runner = CliRunner()


def _repo_with_origin(tmp_path: Path, url: str) -> Path:
    g = tmp_path / ".git"
    g.mkdir(parents=True)
    (g / "config").write_text(textwrap.dedent(f"""\
        [remote "origin"]
            url = {url}
    """))
    return tmp_path


def test_init_alias_yes_writes_envrc_and_gitignore(tmp_path: Path) -> None:
    repo = _repo_with_origin(tmp_path, "git@github.com-16bitdo:16bitdo/x.git")
    result = runner.invoke(
        app, ["project", "init", "--path", str(repo), "--yes", "--no-allow"]
    )
    assert result.exit_code == 0, result.stdout
    assert (repo / ".envrc").read_text() == 'export GH_CONFIG_DIR="$HOME/.config/gh-16bitdo"\n'
    assert ".envrc" in (repo / ".gitignore").read_text()


def test_init_account_override(tmp_path: Path) -> None:
    repo = _repo_with_origin(tmp_path, "git@github.com-16bitdo:16bitdo/x.git")
    result = runner.invoke(
        app,
        ["project", "init", "--path", str(repo), "--account", "custom", "--yes", "--no-allow"],
    )
    assert result.exit_code == 0, result.stdout
    assert 'gh-custom' in (repo / ".envrc").read_text()


def test_init_no_git_errors_without_writing(tmp_path: Path) -> None:
    result = runner.invoke(app, ["project", "init", "--path", str(tmp_path), "--yes"])
    assert result.exit_code == 1
    assert not (tmp_path / ".envrc").exists()


def test_init_yes_undederivable_errors(tmp_path: Path) -> None:
    repo = _repo_with_origin(tmp_path, "https://github.com/acme/x.git")
    result = runner.invoke(
        app, ["project", "init", "--path", str(repo), "--yes", "--no-allow"]
    )
    assert result.exit_code == 1
