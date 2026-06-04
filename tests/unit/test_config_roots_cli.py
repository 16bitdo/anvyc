"""anvyc config roots <verb> CLI 동작 테스트."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from anvyc.cli import app

runner = CliRunner()


def test_roots_list_default_shows_six(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # HOME 격리 → materialize 된 defaults 의 실제 FS discover 회피(헤르메틱).
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("storage:\n  root: .anvyc\n")
    result = runner.invoke(app, ["config", "roots", "list", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "~/dev" in result.stdout
    assert "default" in result.stdout


def test_roots_list_json(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/dev\n")
    result = runner.invoke(app, ["config", "roots", "list", "--config", str(cfg), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["roots"][0]["path"] == "~/dev"
    assert data["roots"][0]["source"] == "explicit"


def test_roots_add_writes_global_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    (home / ".anvyc").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    work = tmp_path / "work"
    work.mkdir()
    result = runner.invoke(app, ["config", "roots", "add", str(work)])
    assert result.exit_code == 0
    written = yaml.safe_load((home / ".anvyc" / "anvyc.yaml").read_text())
    # materialize 된 defaults + 신규 root
    assert "~/dev" in written["project_roots"]
    assert any(str(work) in r or r == "~/work" for r in written["project_roots"])


def test_roots_add_explicit_config(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/dev\n")
    work = tmp_path / "w"
    work.mkdir()
    result = runner.invoke(app, ["config", "roots", "add", str(work), "--config", str(cfg)])
    assert result.exit_code == 0
    assert "added" in result.stdout.lower() or "추가" in result.stdout


def test_roots_rm_removes(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/dev\n  - ~/work\n")
    result = runner.invoke(app, ["config", "roots", "rm", "~/work", "--config", str(cfg)])
    assert result.exit_code == 0
    assert yaml.safe_load(cfg.read_text())["project_roots"] == ["~/dev"]


def test_roots_rm_to_empty_reverts_to_default(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/dev\n")
    result = runner.invoke(app, ["config", "roots", "rm", "~/dev", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "project_roots" not in (yaml.safe_load(cfg.read_text()) or {})
    assert "default" in result.stdout.lower() or "복귀" in result.stdout


def test_roots_clear_reverts(tmp_path: Path) -> None:
    cfg = tmp_path / "anvyc.yaml"
    cfg.write_text("project_roots:\n  - ~/dev\n  - ~/work\n")
    result = runner.invoke(app, ["config", "roots", "clear", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "project_roots" not in (yaml.safe_load(cfg.read_text()) or {})
    # before→after 출력에 default 표시
    assert "~/dev" in result.stdout
